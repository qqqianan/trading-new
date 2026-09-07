"""Frozen contracts for one CAPCO historical membership source audit."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True, slots=True)
class CapcoPdfDocument:
    """Final CAPCO attachment URL and response bytes."""

    url: str
    content: bytes


class CapcoMembershipStatus(StrEnum):
    """Evidence state for one security in one official classification file."""

    FOUND = "FOUND"
    MISSING = "MISSING"


class CapcoMembershipCandidate(BaseModel):
    """Exact parent-linked request for one later CAPCO classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_archive_audit_id: str = Field(pattern=r"^capco_industry_archive_audit_[0-9a-f]{64}$")
    parent_conflict_audit_id: str = Field(pattern=r"^cninfo_industry_bridge_audit_[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^\d{6}\.SH$")
    listing_date: date
    year: int = Field(ge=2000, le=2100)
    half: int = Field(ge=1, le=2)
    publication_date: date
    attachment_url: str = Field(min_length=1)
    expected_attachment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CapcoMembershipEvidence(BaseModel):
    """One unambiguous row recovered from the exact official attachment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_url: str
    attachment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attachment_bytes: int = Field(gt=0)
    security_code: str = Field(pattern=r"^\d{6}$")
    security_name: str
    industry_code: str = Field(pattern=r"^[A-Z]\d{2}$")
    industry_name: str
    page_number: int = Field(gt=0)


class CapcoTemporalResolution(BaseModel):
    """Explicit unknown interval awaiting trading-calendar availability projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unknown_from: date
    provider_publication_date: date
    availability_status: str = Field(pattern=r"^PENDING_NEXT_TRADING_SESSION_OPEN$")


class CapcoMembershipAudit(BaseModel):
    """Content-addressed source audit that never authorizes research use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(pattern=r"^capco_membership_audit_[0-9a-f]{64}$")
    audit_version: str
    audited_at: datetime
    candidate: CapcoMembershipCandidate
    status: CapcoMembershipStatus
    failure_reason: str | None
    evidence: CapcoMembershipEvidence | None
    temporal_resolution: CapcoTemporalResolution
    research_use_authorized: bool

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        """Make positive evidence and failure states mutually exclusive."""
        found = self.status is CapcoMembershipStatus.FOUND and self.evidence is not None
        missing = self.status is CapcoMembershipStatus.MISSING and self.failure_reason is not None
        if not (found or missing):
            message = "CAPCO membership status must match evidence or failure reason"
            raise ValueError(message)
        return self
