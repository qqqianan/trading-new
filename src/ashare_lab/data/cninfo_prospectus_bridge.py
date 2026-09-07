"""Supplemental source-only industry audit using official IPO prospectuses."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeStatus,
    CninfoBridgeEvidence,
    TimestampPrecision,
    classify_provider_timestamp,
)
from ashare_lab.data.cninfo_industry_parser import (
    AnnouncementSelectionError,
    IndustryDisclosureError,
    IndustryDisclosureFailure,
    parse_industry_disclosure,
    select_prospectus,
)
from ashare_lab.data.cninfo_pdf import PdfExtractionError, extract_pdf_text

_AUDIT_VERSION: Final = "cninfo_prospectus_bridge_audit_v6"
_TRACE_REQUIRED_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "cninfo_prospectus_bridge_audit_v4",
        "cninfo_prospectus_bridge_audit_v5",
        "cninfo_prospectus_bridge_audit_v6",
    }
)
PdfTextExtractor = Callable[[bytes], str]


class ProspectusBridgeCandidate(BaseModel):
    """One base-audit miss eligible for deterministic prospectus supplementation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_audit_id: str = Field(pattern=r"^cninfo_industry_bridge_audit_[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    listing_date: date


class ProspectusSourceTrace(BaseModel):
    """Exact query and selected-document hashes retained for every outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    security_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    org_id: str | None
    announcement_response_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    announcement_id: str | None
    announcement_title: str | None
    provider_announced_at: datetime | None
    timestamp_precision: TimestampPrecision | None
    pdf_url: str | None
    pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pdf_bytes: int | None = Field(default=None, gt=0)


class CninfoProspectusBridgeAudit(BaseModel):
    """Content-addressed supplemental report linked to one failed base audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(pattern=r"^cninfo_prospectus_bridge_audit_[0-9a-f]{64}$")
    audit_version: str
    audited_at: datetime
    candidate: ProspectusBridgeCandidate
    status: BridgeStatus
    failure_reason: str | None
    evidence: CninfoBridgeEvidence | None
    trace: ProspectusSourceTrace | None = None
    research_use_authorized: bool

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        """Require exactly one evidence or failure branch."""
        valid_found = self.status is BridgeStatus.FOUND and self.evidence is not None
        valid_missing = self.status is BridgeStatus.MISSING and self.failure_reason is not None
        if not (valid_found or valid_missing):
            msg = "prospectus bridge status must match evidence or failure reason"
            raise ValueError(msg)
        if self.audit_version in _TRACE_REQUIRED_VERSIONS and self.trace is None:
            msg = "current prospectus audit requires source trace"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class _ProspectusAuditOutcome:
    status: BridgeStatus
    failure_reason: str | None
    evidence: CninfoBridgeEvidence | None
    trace: ProspectusSourceTrace


def audit_cninfo_prospectus_candidate(
    provider: CninfoArchiveClient,
    candidate: ProspectusBridgeCandidate,
    *,
    audited_at: datetime,
    text_extractor: PdfTextExtractor = extract_pdf_text,
) -> CninfoProspectusBridgeAudit:
    """Audit one parent miss without changing or replacing its base evidence."""
    code = candidate.symbol.split(".", maxsplit=1)[0]
    security = provider.lookup_security(code)
    security_sha256 = hashlib.sha256(security.payload).hexdigest()
    exact_hits = tuple(hit for hit in security.hits if hit.code == code)
    if len(exact_hits) != 1:
        trace = ProspectusSourceTrace(
            security_response_sha256=security_sha256,
            org_id=None,
            announcement_response_sha256=None,
            announcement_id=None,
            announcement_title=None,
            provider_announced_at=None,
            timestamp_precision=None,
            pdf_url=None,
            pdf_sha256=None,
            pdf_bytes=None,
        )
        return _missing(candidate, audited_at, "security_identity_not_unique", trace)
    hit = exact_hits[0]
    lookup = provider.search_prospectuses(code, hit.org_id, candidate.listing_date)
    announcement_sha256 = hashlib.sha256(lookup.payload).hexdigest()
    query_trace = ProspectusSourceTrace(
        security_response_sha256=security_sha256,
        org_id=hit.org_id,
        announcement_response_sha256=announcement_sha256,
        announcement_id=None,
        announcement_title=None,
        provider_announced_at=None,
        timestamp_precision=None,
        pdf_url=None,
        pdf_sha256=None,
        pdf_bytes=None,
    )
    try:
        selected = select_prospectus(lookup.payload)
    except AnnouncementSelectionError:
        return _missing(candidate, audited_at, "final_prospectus_missing", query_trace)
    pdf = provider.fetch_pdf(selected.adjunct_url)
    announced_at, precision = classify_provider_timestamp(selected.announcement_time_ms)
    selected_trace = ProspectusSourceTrace(
        security_response_sha256=security_sha256,
        org_id=hit.org_id,
        announcement_response_sha256=announcement_sha256,
        announcement_id=selected.announcement_id,
        announcement_title=selected.title,
        provider_announced_at=announced_at,
        timestamp_precision=precision,
        pdf_url=pdf.url,
        pdf_sha256=hashlib.sha256(pdf.content).hexdigest(),
        pdf_bytes=len(pdf.content),
    )
    if not pdf.content.startswith(b"%PDF"):
        return _missing(candidate, audited_at, "selected_attachment_is_not_pdf", selected_trace)
    try:
        text = text_extractor(pdf.content)
    except PdfExtractionError:
        return _missing(candidate, audited_at, "pdf_text_extraction_failed", selected_trace)
    try:
        disclosure = parse_industry_disclosure(text)
    except IndustryDisclosureError as error:
        match error.reason:
            case IndustryDisclosureFailure.MISSING:
                reason = "explicit_industry_disclosure_missing"
            case IndustryDisclosureFailure.CONFLICTING:
                reason = "explicit_industry_disclosure_conflicting"
        return _missing(candidate, audited_at, reason, selected_trace)
    evidence = CninfoBridgeEvidence(
        symbol=candidate.symbol,
        listing_date=candidate.listing_date,
        org_id=hit.org_id,
        security_response_sha256=hashlib.sha256(security.payload).hexdigest(),
        announcement_response_sha256=hashlib.sha256(lookup.payload).hexdigest(),
        announcement_id=selected.announcement_id,
        announcement_title=selected.title,
        provider_announced_at=announced_at,
        timestamp_precision=precision,
        pdf_url=pdf.url,
        pdf_sha256=hashlib.sha256(pdf.content).hexdigest(),
        pdf_bytes=len(pdf.content),
        taxonomy=disclosure.taxonomy,
        industry_code=disclosure.industry_code,
        industry_name=disclosure.industry_name,
        matched_disclosure=disclosure.matched_text,
    )
    outcome = _ProspectusAuditOutcome(
        status=BridgeStatus.FOUND,
        failure_reason=None,
        evidence=evidence,
        trace=selected_trace,
    )
    return _report(candidate, audited_at, outcome)


def _missing(
    candidate: ProspectusBridgeCandidate,
    audited_at: datetime,
    reason: str,
    trace: ProspectusSourceTrace,
) -> CninfoProspectusBridgeAudit:
    outcome = _ProspectusAuditOutcome(
        status=BridgeStatus.MISSING,
        failure_reason=reason,
        evidence=None,
        trace=trace,
    )
    return _report(candidate, audited_at, outcome)


def _report(
    candidate: ProspectusBridgeCandidate,
    audited_at: datetime,
    outcome: _ProspectusAuditOutcome,
) -> CninfoProspectusBridgeAudit:
    draft = CninfoProspectusBridgeAudit(
        audit_id=f"cninfo_prospectus_bridge_audit_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        audited_at=audited_at,
        candidate=candidate,
        status=outcome.status,
        failure_reason=outcome.failure_reason,
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
    return draft.model_copy(update={"audit_id": f"cninfo_prospectus_bridge_audit_{digest}"})
