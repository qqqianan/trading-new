"""Source-only audit for IPO industry disclosures found through CNInfo."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Final, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_parser import (
    AnnouncementSelectionError,
    IndustryDisclosureError,
    IndustryDisclosureFailure,
    parse_industry_disclosure,
    select_listing_announcement,
)
from ashare_lab.data.cninfo_pdf import PdfExtractionError, extract_pdf_text

_AUDIT_VERSION: Final = "cninfo_industry_bridge_audit_v8"
_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
PdfTextExtractor = Callable[[bytes], str]


class BridgeStatus(StrEnum):
    """Source evidence state for one listing candidate."""

    FOUND = "FOUND"
    MISSING = "MISSING"


class TimestampPrecision(StrEnum):
    """Provider timestamp precision requiring different PIT projection."""

    EXACT_MILLISECOND = "EXACT_MILLISECOND"
    DATE_ONLY = "DATE_ONLY"


class BridgeCandidate(BaseModel):
    """One historical listing requiring initial industry evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    listing_date: date


class CninfoBridgeEvidence(BaseModel):
    """Exact query, PDF, time, and industry evidence for one listing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    listing_date: date
    org_id: str
    security_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    announcement_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    announcement_id: str
    announcement_title: str
    provider_announced_at: datetime
    timestamp_precision: TimestampPrecision
    pdf_url: str
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_bytes: int = Field(gt=0)
    taxonomy: str
    industry_code: str = Field(pattern=r"^[A-Z]\d{2}$")
    industry_name: str
    matched_disclosure: str


class CninfoIndustryBridgeAudit(BaseModel):
    """Content-addressed pilot report that cannot authorize research use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(pattern=r"^cninfo_industry_bridge_audit_[0-9a-f]{64}$")
    audit_version: str
    audited_at: datetime
    candidate: BridgeCandidate
    status: BridgeStatus
    failure_reason: str | None
    evidence: CninfoBridgeEvidence | None
    research_use_authorized: bool

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        """Make covered and missing report states mutually exclusive."""
        valid_found = self.status is BridgeStatus.FOUND and self.evidence is not None
        valid_missing = self.status is BridgeStatus.MISSING and self.failure_reason is not None
        if not (valid_found or valid_missing):
            msg = "bridge status must match evidence or failure reason"
            raise ValueError(msg)
        return self


def audit_cninfo_candidate(
    provider: CninfoArchiveClient,
    candidate: BridgeCandidate,
    *,
    audited_at: datetime,
    text_extractor: PdfTextExtractor = extract_pdf_text,
) -> CninfoIndustryBridgeAudit:
    """Audit one candidate without persisting or authorizing industry data."""
    code = candidate.symbol.split(".", maxsplit=1)[0]
    security = provider.lookup_security(code)
    exact_hits = tuple(hit for hit in security.hits if hit.code == code)
    if len(exact_hits) != 1:
        return _missing(candidate, audited_at, "security_identity_not_unique")
    hit = exact_hits[0]
    lookup = provider.search_listing_announcements(code, hit.org_id, candidate.listing_date)
    try:
        selected = select_listing_announcement(lookup.payload)
    except AnnouncementSelectionError:
        return _missing(candidate, audited_at, "final_listing_announcement_missing")
    pdf = provider.fetch_pdf(selected.adjunct_url)
    if not pdf.content.startswith(b"%PDF"):
        return _missing(candidate, audited_at, "selected_attachment_is_not_pdf")
    try:
        text = text_extractor(pdf.content)
    except PdfExtractionError:
        return _missing(candidate, audited_at, "pdf_text_extraction_failed")
    try:
        disclosure = parse_industry_disclosure(text)
    except IndustryDisclosureError as error:
        match error.reason:
            case IndustryDisclosureFailure.MISSING:
                reason = "explicit_industry_disclosure_missing"
            case IndustryDisclosureFailure.CONFLICTING:
                reason = "explicit_industry_disclosure_conflicting"
        return _missing(candidate, audited_at, reason)
    announced_at, precision = classify_provider_timestamp(selected.announcement_time_ms)
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
    return _report(candidate, audited_at, BridgeStatus.FOUND, None, evidence)


def classify_provider_timestamp(timestamp_ms: int) -> tuple[datetime, TimestampPrecision]:
    """Classify provider midnight as date-only in its local publication timezone."""
    announced_at = datetime.fromtimestamp(timestamp_ms / 1000, UTC).astimezone(_SHANGHAI)
    precision = (
        TimestampPrecision.DATE_ONLY
        if announced_at.timetz().replace(tzinfo=None) == time()
        else TimestampPrecision.EXACT_MILLISECOND
    )
    return announced_at, precision


def _missing(
    candidate: BridgeCandidate,
    audited_at: datetime,
    reason: str,
) -> CninfoIndustryBridgeAudit:
    return _report(candidate, audited_at, BridgeStatus.MISSING, reason, None)


def _report(
    candidate: BridgeCandidate,
    audited_at: datetime,
    status: BridgeStatus,
    failure_reason: str | None,
    evidence: CninfoBridgeEvidence | None,
) -> CninfoIndustryBridgeAudit:
    draft = CninfoIndustryBridgeAudit(
        audit_id=f"cninfo_industry_bridge_audit_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        audited_at=audited_at,
        candidate=candidate,
        status=status,
        failure_reason=failure_reason,
        evidence=evidence,
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"audit_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"audit_id": f"cninfo_industry_bridge_audit_{digest}"})
