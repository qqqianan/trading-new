"""Frozen source-audit contracts for SSE prospectus industry evidence."""

from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.data.cninfo_industry_bridge import BridgeStatus


class SseProspectusCandidate(BaseModel):
    """One unresolved CNInfo observation eligible for independent confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_consistency_id: str = Field(
        pattern=r"^cninfo_prospectus_consistency_audit_[0-9a-f]{64}$"
    )
    cninfo_announcement_id: str = Field(min_length=1)
    expected_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^\d{6}\.SH$")
    listing_date: date


class SseSourceTrace(BaseModel):
    """Exact SSE query and selected attachment retained for every outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str | None
    provider_recorded_at: datetime | None
    disclosure_date: date | None
    pdf_url: str | None
    pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pdf_bytes: int | None = Field(default=None, gt=0)


class SseIndustryEvidence(BaseModel):
    """Official exchange document identity and explicit industry disclosure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    security_code: str
    security_name: str
    title: str
    provider_recorded_at: datetime
    disclosure_date: date
    pdf_url: str
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_bytes: int = Field(gt=0)
    taxonomy: str
    industry_code: str = Field(pattern=r"^[A-Z]\d{2}$")
    industry_name: str
    matched_disclosure: str


class SseProspectusIndustryAudit(BaseModel):
    """Content-addressed independent source report without research authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(pattern=r"^sse_prospectus_industry_audit_[0-9a-f]{64}$")
    audit_version: str
    audited_at: datetime
    candidate: SseProspectusCandidate
    status: BridgeStatus
    failure_reason: str | None
    evidence: SseIndustryEvidence | None
    trace: SseSourceTrace
    research_use_authorized: bool

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        """Require exactly one positive-evidence or failure branch."""
        found = self.status is BridgeStatus.FOUND and self.evidence is not None
        missing = self.status is BridgeStatus.MISSING and self.failure_reason is not None
        if not (found or missing):
            message = "SSE audit status must match evidence or failure reason"
            raise ValueError(message)
        return self
