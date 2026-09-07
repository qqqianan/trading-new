"""Typed contracts for CNInfo repeated-observation source audits."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.cninfo_prospectus_bridge import ProspectusBridgeCandidate


class QueryOutcome(StrEnum):
    """Normalized result of one exact prospectus discovery query."""

    FOUND = "FOUND"
    EMPTY = "EMPTY"


class ConsistencyStatus(StrEnum):
    """Governed conclusion across all retained query observations."""

    STABLE_FOUND = "STABLE_FOUND"
    STABLE_EMPTY = "STABLE_EMPTY"
    INSUFFICIENT = "INSUFFICIENT"
    UNSTABLE = "UNSTABLE"


class ProspectusQuerySpec(BaseModel):
    """Exact natural query whose repeated observations are comparable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_id: str = Field(pattern=r"^cninfo_prospectus_query_[0-9a-f]{64}$")
    query_version: str
    code: str = Field(pattern=r"^\d{6}$")
    org_id: str = Field(min_length=1)
    search_key: str
    start_date: date
    end_date: date
    page_size: int = Field(gt=0)
    tab_name: str


class ProspectusQueryObservation(BaseModel):
    """One immutable provider response normalized without discarding raw hashes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_audit_id: str = Field(pattern=r"^cninfo_prospectus_bridge_audit_[0-9a-f]{64}$")
    source_audit_version: str
    observed_at: datetime
    security_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    announcement_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: QueryOutcome
    announcement_id: str | None
    pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CninfoProspectusConsistencyAudit(BaseModel):
    """Content-addressed repeated-observation conclusion with no research authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    consistency_id: str = Field(pattern=r"^cninfo_prospectus_consistency_audit_[0-9a-f]{64}$")
    audit_version: str
    assessed_at: datetime
    candidate: ProspectusBridgeCandidate
    query: ProspectusQuerySpec
    observations: tuple[ProspectusQueryObservation, ...]
    minimum_observations: int = Field(ge=2)
    status: ConsistencyStatus
    reason: str | None
    stable_announcement_id: str | None
    stable_pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    research_use_authorized: bool


class ProspectusConsistencyError(Exception):
    """Source audits cannot form one exact repeated-query evidence set."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one fail-closed comparison error."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the source boundary and non-secret failure detail."""
        return f"cninfo_prospectus_consistency: {self.detail}"
