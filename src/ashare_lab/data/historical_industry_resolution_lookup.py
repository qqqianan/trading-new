"""Unique parent-key indexes for historical-industry source resolution."""

from dataclasses import dataclass

from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.cninfo_observation_models import CninfoProspectusConsistencyAudit
from ashare_lab.data.cninfo_prospectus_bridge import CninfoProspectusBridgeAudit
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionError,
)
from ashare_lab.data.sse_industry_models import SseProspectusIndustryAudit


@dataclass(frozen=True, slots=True)
class ResolutionLookup:
    """Every optional source branch indexed by its exact required parent."""

    supplements: dict[str, CninfoProspectusBridgeAudit]
    consistencies: dict[str, CninfoProspectusConsistencyAudit]
    sse_audits: dict[str, SseProspectusIndustryAudit]
    capco_audits: dict[str, CapcoMembershipAudit]


def build_resolution_lookup(
    supplements: tuple[CninfoProspectusBridgeAudit, ...],
    consistencies: tuple[CninfoProspectusConsistencyAudit, ...],
    sse_audits: tuple[SseProspectusIndustryAudit, ...],
    capco_audits: tuple[CapcoMembershipAudit, ...],
) -> ResolutionLookup:
    """Build exact indexes and reject every duplicate parent key."""
    return ResolutionLookup(
        supplements=_unique(
            tuple((audit.candidate.parent_audit_id, audit) for audit in supplements)
        ),
        consistencies=_unique(
            tuple((audit.candidate.parent_audit_id, audit) for audit in consistencies)
        ),
        sse_audits=_unique(
            tuple((audit.candidate.parent_consistency_id, audit) for audit in sse_audits)
        ),
        capco_audits=_unique(
            tuple((audit.candidate.parent_conflict_audit_id, audit) for audit in capco_audits)
        ),
    )


def required[T](mapping: dict[str, T], key: str, label: str) -> T:
    """Read one required exact parent or fail closed without fallback."""
    try:
        return mapping[key]
    except KeyError:
        detail = f"missing {label}: {key}"
        raise HistoricalIndustryResolutionError(detail) from None


def _unique[T](pairs: tuple[tuple[str, T], ...]) -> dict[str, T]:
    if len(pairs) != len({key for key, _value in pairs}):
        detail = "duplicate source parent key"
        raise HistoricalIndustryResolutionError(detail)
    return dict(pairs)
