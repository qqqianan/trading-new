"""Source-only industry audit using official SSE prospectus evidence."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from ashare_lab.data.cninfo_industry_bridge import BridgeStatus
from ashare_lab.data.cninfo_industry_parser import (
    IndustryDisclosureError,
    IndustryDisclosureFailure,
    parse_industry_disclosure,
)
from ashare_lab.data.cninfo_observation_models import (
    CninfoProspectusConsistencyAudit,
    ConsistencyStatus,
    QueryOutcome,
)
from ashare_lab.data.cninfo_pdf import PdfExtractionError, extract_pdf_text
from ashare_lab.data.sse_industry_models import (
    SseIndustryEvidence,
    SseProspectusCandidate,
    SseProspectusIndustryAudit,
    SseSourceTrace,
)
from ashare_lab.data.sse_models import SseBulletin, SseBulletinLookup, SsePdfDocument

_AUDIT_VERSION: Final = "sse_prospectus_industry_audit_v2"
_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_EXCLUDED_TITLES: Final = ("摘要", "更正", "申报稿", "预披露", "提示性公告", "已取消")
PdfTextExtractor = Callable[[bytes], str]


class SseArchiveProvider(Protocol):
    """Minimal official-source capability required by the audit."""

    def search_prospectuses(self, code: str) -> SseBulletinLookup:
        """Return exact official query bytes and parsed bulletin rows."""
        ...

    def fetch_pdf(self, attachment_url: str) -> SsePdfDocument:
        """Return exact selected attachment bytes and effective URL."""
        ...


class SseSourceLinkError(Exception):
    """The independent audit is not linked to an exact CNInfo contradiction."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one fail-closed parent-link error."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the independent-source boundary and detail."""
        return f"sse_source_link: {self.detail}"


@dataclass(frozen=True, slots=True)
class _SseAuditOutcome:
    status: BridgeStatus
    reason: str | None
    evidence: SseIndustryEvidence | None
    trace: SseSourceTrace


def candidate_from_cninfo_consistency(
    parent: CninfoProspectusConsistencyAudit,
) -> SseProspectusCandidate:
    """Open independent confirmation only for an exact outcome contradiction."""
    valid_parent = (
        parent.status is ConsistencyStatus.UNSTABLE and parent.reason == "query_outcome_changed"
    )
    if not valid_parent:
        detail = "parent is not an unstable CNInfo query contradiction"
        raise SseSourceLinkError(detail)
    if not parent.candidate.symbol.endswith(".SH"):
        detail = "SSE source cannot audit a non-SH candidate"
        raise SseSourceLinkError(detail)
    documents = {
        (observation.announcement_id, observation.pdf_sha256)
        for observation in parent.observations
        if observation.outcome is QueryOutcome.FOUND
    }
    if len(documents) != 1:
        detail = "parent has no unique successful CNInfo document identity"
        raise SseSourceLinkError(detail)
    announcement_id, pdf_sha256 = documents.pop()
    if announcement_id is None or pdf_sha256 is None:
        detail = "parent successful observation lacks exact document hashes"
        raise SseSourceLinkError(detail)
    return SseProspectusCandidate(
        parent_consistency_id=parent.consistency_id,
        cninfo_announcement_id=announcement_id,
        expected_pdf_sha256=pdf_sha256,
        symbol=parent.candidate.symbol,
        listing_date=parent.candidate.listing_date,
    )


def audit_sse_prospectus_candidate(
    provider: SseArchiveProvider,
    candidate: SseProspectusCandidate,
    *,
    audited_at: datetime,
    text_extractor: PdfTextExtractor = extract_pdf_text,
) -> SseProspectusIndustryAudit:
    """Audit one independent exchange document without writing research data."""
    code = candidate.symbol.split(".", maxsplit=1)[0]
    lookup = provider.search_prospectuses(code)
    query_hash = hashlib.sha256(lookup.payload).hexdigest()
    matches = tuple(
        item
        for item in lookup.hits
        if item.security_code == code
        and "招股说明书" in item.title
        and not any(excluded in item.title for excluded in _EXCLUDED_TITLES)
    )
    if len(matches) != 1:
        return _missing(candidate, audited_at, query_hash, "final_prospectus_not_unique")
    selected = matches[0]
    recorded_at = _recorded_at(selected)
    pdf = provider.fetch_pdf(selected.attachment_url)
    trace = _trace(query_hash, selected, recorded_at, pdf)
    if not pdf.content.startswith(b"%PDF"):
        return _missing_with_trace(candidate, audited_at, "selected_attachment_is_not_pdf", trace)
    if trace.pdf_sha256 != candidate.expected_pdf_sha256:
        return _missing_with_trace(
            candidate,
            audited_at,
            "cross_source_pdf_hash_mismatch",
            trace,
        )
    try:
        text = text_extractor(pdf.content)
    except PdfExtractionError:
        return _missing_with_trace(candidate, audited_at, "pdf_text_extraction_failed", trace)
    try:
        disclosure = parse_industry_disclosure(text)
    except IndustryDisclosureError as error:
        match error.reason:
            case IndustryDisclosureFailure.MISSING:
                reason = "explicit_industry_disclosure_missing"
            case IndustryDisclosureFailure.CONFLICTING:
                reason = "explicit_industry_disclosure_conflicting"
        return _missing_with_trace(candidate, audited_at, reason, trace)
    evidence = SseIndustryEvidence(
        query_response_sha256=query_hash,
        security_code=selected.security_code,
        security_name=selected.security_name,
        title=selected.title,
        provider_recorded_at=recorded_at,
        disclosure_date=selected.disclosure_date,
        pdf_url=pdf.url,
        pdf_sha256=hashlib.sha256(pdf.content).hexdigest(),
        pdf_bytes=len(pdf.content),
        taxonomy=disclosure.taxonomy,
        industry_code=disclosure.industry_code,
        industry_name=disclosure.industry_name,
        matched_disclosure=disclosure.matched_text,
    )
    outcome = _SseAuditOutcome(BridgeStatus.FOUND, None, evidence, trace)
    return _report(candidate, audited_at, outcome)


def _missing(
    candidate: SseProspectusCandidate,
    audited_at: datetime,
    query_hash: str,
    reason: str,
) -> SseProspectusIndustryAudit:
    trace = SseSourceTrace(
        query_response_sha256=query_hash,
        title=None,
        provider_recorded_at=None,
        disclosure_date=None,
        pdf_url=None,
        pdf_sha256=None,
        pdf_bytes=None,
    )
    return _missing_with_trace(candidate, audited_at, reason, trace)


def _missing_with_trace(
    candidate: SseProspectusCandidate,
    audited_at: datetime,
    reason: str,
    trace: SseSourceTrace,
) -> SseProspectusIndustryAudit:
    outcome = _SseAuditOutcome(BridgeStatus.MISSING, reason, None, trace)
    return _report(candidate, audited_at, outcome)


def _report(
    candidate: SseProspectusCandidate,
    audited_at: datetime,
    outcome: _SseAuditOutcome,
) -> SseProspectusIndustryAudit:
    draft = SseProspectusIndustryAudit(
        audit_id=f"sse_prospectus_industry_audit_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        audited_at=audited_at,
        candidate=candidate,
        status=outcome.status,
        failure_reason=outcome.reason,
        evidence=outcome.evidence,
        trace=outcome.trace,
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"audit_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"audit_id": f"sse_prospectus_industry_audit_{digest}"})


def _trace(
    query_hash: str,
    selected: SseBulletin,
    recorded_at: datetime,
    pdf: SsePdfDocument,
) -> SseSourceTrace:
    return SseSourceTrace(
        query_response_sha256=query_hash,
        title=selected.title,
        provider_recorded_at=recorded_at,
        disclosure_date=selected.disclosure_date,
        pdf_url=pdf.url,
        pdf_sha256=hashlib.sha256(pdf.content).hexdigest(),
        pdf_bytes=len(pdf.content),
    )


def _recorded_at(selected: SseBulletin) -> datetime:
    if selected.added_at.tzinfo is None:
        return selected.added_at.replace(tzinfo=_SHANGHAI)
    return selected.added_at.astimezone(_SHANGHAI)
