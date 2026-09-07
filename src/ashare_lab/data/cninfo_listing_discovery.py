"""Stage-one CNInfo identity and listing-announcement discovery."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Final, Self

import httpx2
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_bridge import (
    TimestampPrecision,
    classify_provider_timestamp,
)
from ashare_lab.data.cninfo_industry_parser import (
    AnnouncementSelectionError,
    select_listing_announcement,
)
from ashare_lab.data.cninfo_models import CninfoAnnouncementLookup, CninfoSecurityLookup
from ashare_lab.data.official_bridge_candidates import OfficialBridgeCandidate

_AUDIT_VERSION: Final = "cninfo_listing_discovery_v1"


class CninfoDiscoveryStatus(StrEnum):
    """Closed discovery outcome before any PDF is downloaded."""

    SELECTED = "SELECTED"
    MISSING = "MISSING"


class CninfoDiscoveryStage(StrEnum):
    """Provider operation that produced a retained transient failure."""

    SECURITY_LOOKUP = "SECURITY_LOOKUP"
    ANNOUNCEMENT_LOOKUP = "ANNOUNCEMENT_LOOKUP"


class CninfoDiscoveryFailureTrace(BaseModel):
    """Wire-level evidence for an HTTP or transport failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: CninfoDiscoveryStage
    http_status: int | None = Field(default=None, ge=100, le=599)
    security_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CninfoListingDiscoveryEvidence(BaseModel):
    """Exact response hashes and selected final PDF descriptor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    org_id: str = Field(min_length=1)
    security_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    announcement_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    announcement_id: str = Field(min_length=1)
    announcement_title: str = Field(min_length=1)
    provider_announced_at: datetime
    timestamp_precision: TimestampPrecision
    pdf_url: str = Field(pattern=r"^https://static\.cninfo\.com\.cn/.+")


class CninfoListingDiscoveryAudit(BaseModel):
    """Content-addressed discovery result retaining failures in place."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(pattern=r"^cninfo_listing_discovery_[0-9a-f]{64}$")
    audit_version: str
    discovered_at: datetime
    candidate: OfficialBridgeCandidate
    status: CninfoDiscoveryStatus
    failure_reason: str | None
    failure_trace: CninfoDiscoveryFailureTrace | None = None
    evidence: CninfoListingDiscoveryEvidence | None
    research_use_authorized: bool

    @model_validator(mode="after")
    def outcome_matches_evidence(self) -> Self:
        """Keep selected and missing discovery states mutually exclusive."""
        selected = (
            self.status is CninfoDiscoveryStatus.SELECTED
            and self.evidence is not None
            and self.failure_reason is None
            and self.failure_trace is None
        )
        missing = (
            self.status is CninfoDiscoveryStatus.MISSING
            and self.failure_reason is not None
            and self.evidence is None
        )
        if not (selected or missing) or self.research_use_authorized:
            message = "discovery outcome, evidence, or research authority differs"
            raise ValueError(message)
        return self


def discover_cninfo_listing(
    provider: CninfoArchiveClient,
    candidate: OfficialBridgeCandidate,
    *,
    discovered_at: datetime,
) -> CninfoListingDiscoveryAudit:
    """Select an official listing PDF without downloading its bytes."""
    code = candidate.symbol.split(".", maxsplit=1)[0]
    security_result = _lookup_security(provider, code, candidate, discovered_at)
    match security_result:
        case CninfoListingDiscoveryAudit():
            return security_result
        case CninfoSecurityLookup():
            security = security_result
    exact_hits = tuple(hit for hit in security.hits if hit.code == code)
    if len(exact_hits) != 1:
        return _report(candidate, discovered_at, "security_identity_not_unique", None, None)
    hit = exact_hits[0]
    security_sha256 = hashlib.sha256(security.payload).hexdigest()
    lookup_result = _lookup_announcement(
        provider,
        hit.org_id,
        candidate,
        discovered_at,
        security_sha256,
    )
    match lookup_result:
        case CninfoListingDiscoveryAudit():
            return lookup_result
        case CninfoAnnouncementLookup():
            lookup = lookup_result
    try:
        selected = select_listing_announcement(lookup.payload)
    except AnnouncementSelectionError:
        return _report(
            candidate,
            discovered_at,
            "final_listing_announcement_missing",
            None,
            None,
        )
    announced_at, precision = classify_provider_timestamp(selected.announcement_time_ms)
    evidence = CninfoListingDiscoveryEvidence(
        org_id=hit.org_id,
        security_response_sha256=security_sha256,
        announcement_response_sha256=hashlib.sha256(lookup.payload).hexdigest(),
        announcement_id=selected.announcement_id,
        announcement_title=selected.title,
        provider_announced_at=announced_at,
        timestamp_precision=precision,
        pdf_url=provider.resolve_pdf_url(selected.adjunct_url),
    )
    return _report(candidate, discovered_at, None, None, evidence)


def _lookup_security(
    provider: CninfoArchiveClient,
    code: str,
    candidate: OfficialBridgeCandidate,
    discovered_at: datetime,
) -> CninfoSecurityLookup | CninfoListingDiscoveryAudit:
    try:
        return provider.lookup_security(code)
    except httpx2.HTTPStatusError as error:
        trace = _http_failure_trace(CninfoDiscoveryStage.SECURITY_LOOKUP, error, None)
        return _report(candidate, discovered_at, "provider_http_error", trace, None)
    except httpx2.TransportError:
        trace = CninfoDiscoveryFailureTrace(stage=CninfoDiscoveryStage.SECURITY_LOOKUP)
        return _report(candidate, discovered_at, "provider_transport_error", trace, None)


def _lookup_announcement(
    provider: CninfoArchiveClient,
    org_id: str,
    candidate: OfficialBridgeCandidate,
    discovered_at: datetime,
    security_sha256: str,
) -> CninfoAnnouncementLookup | CninfoListingDiscoveryAudit:
    code = candidate.symbol.split(".", maxsplit=1)[0]
    try:
        return provider.search_listing_announcements(code, org_id, candidate.listing_date)
    except httpx2.HTTPStatusError as error:
        trace = _http_failure_trace(
            CninfoDiscoveryStage.ANNOUNCEMENT_LOOKUP,
            error,
            security_sha256,
        )
        return _report(candidate, discovered_at, "provider_http_error", trace, None)
    except httpx2.TransportError:
        trace = CninfoDiscoveryFailureTrace(
            stage=CninfoDiscoveryStage.ANNOUNCEMENT_LOOKUP,
            security_response_sha256=security_sha256,
        )
        return _report(candidate, discovered_at, "provider_transport_error", trace, None)


def _report(
    candidate: OfficialBridgeCandidate,
    discovered_at: datetime,
    failure_reason: str | None,
    failure_trace: CninfoDiscoveryFailureTrace | None,
    evidence: CninfoListingDiscoveryEvidence | None,
) -> CninfoListingDiscoveryAudit:
    status = (
        CninfoDiscoveryStatus.SELECTED if evidence is not None else CninfoDiscoveryStatus.MISSING
    )
    draft = CninfoListingDiscoveryAudit(
        audit_id=f"cninfo_listing_discovery_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        discovered_at=discovered_at,
        candidate=candidate,
        status=status,
        failure_reason=failure_reason,
        failure_trace=failure_trace,
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
    return draft.model_copy(update={"audit_id": f"cninfo_listing_discovery_{digest}"})


def _http_failure_trace(
    stage: CninfoDiscoveryStage,
    error: httpx2.HTTPStatusError,
    security_response_sha256: str | None,
) -> CninfoDiscoveryFailureTrace:
    return CninfoDiscoveryFailureTrace(
        stage=stage,
        http_status=error.response.status_code,
        security_response_sha256=security_response_sha256,
        response_sha256=hashlib.sha256(error.response.content).hexdigest(),
    )
