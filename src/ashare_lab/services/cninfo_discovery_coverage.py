"""Verify explicit discovery shards before any second-stage document audit."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ashare_lab.data.cninfo_listing_discovery import CninfoListingDiscoveryAudit
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection
from ashare_lab.services.cninfo_full_discovery import (
    CninfoFullDiscoveryError,
    CninfoFullDiscoveryPlan,
    CninfoFullDiscoveryShard,
    build_full_discovery_plan,
    build_full_discovery_shard,
    freeze_full_candidate_selection,
)


class DiscoveryFailure(BaseModel):
    """One retained unsuccessful observation in the frozen population."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    audit_id: str
    reason: str


class CninfoDiscoveryCoverage(BaseModel):
    """Discovery completeness, explicitly separate from research admissibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    report_version: Literal["cninfo_discovery_coverage_v1"]
    selection_id: str
    plan_id: str
    shard_ids: tuple[str, ...]
    candidate_universe_sha256: str
    candidate_count: int
    observed_count: int
    unobserved_count: int
    selected_count: int
    missing_count: int
    missing_shard_indices: tuple[int, ...]
    failures: tuple[DiscoveryFailure, ...]
    status: Literal["COMPLETE_DISCOVERY", "INCOMPLETE_DISCOVERY"]
    research_use_authorized: Literal[False] = False


def build_discovery_coverage(
    selection: StratifiedCandidateSelection,
    plan: CninfoFullDiscoveryPlan,
    shards: tuple[CninfoFullDiscoveryShard, ...],
) -> CninfoDiscoveryCoverage:
    """Recompute every identity and retain missing observations without replacement."""
    if freeze_full_candidate_selection(selection.selected) != selection:
        detail = "selection content differs from its identity"
        raise CninfoFullDiscoveryError(detail)
    expected_plan = build_full_discovery_plan(
        selection, shard_size=plan.shard_size, planned_at=plan.planned_at
    )
    if expected_plan != plan:
        detail = "plan content differs from its identity"
        raise CninfoFullDiscoveryError(detail)
    indices = tuple(shard.shard_index for shard in shards)
    if len(indices) != len(set(indices)):
        detail = "duplicate shard observations require separate review"
        raise CninfoFullDiscoveryError(detail)
    ordered = tuple(sorted(shards, key=lambda item: item.shard_index))
    for shard in ordered:
        rebuilt = build_full_discovery_shard(
            plan,
            selection,
            shard_index=shard.shard_index,
            audits=shard.audits,
            completed_at=shard.completed_at,
        )
        if rebuilt != shard:
            detail = "shard identity, counts, or parents differ"
            raise CninfoFullDiscoveryError(detail)
        spec = plan.shards[shard.shard_index]
        expected = selection.selected[spec.start_offset : spec.end_offset_exclusive]
        if tuple(audit.candidate for audit in shard.audits) != expected:
            detail = "candidate lifecycle lineage differs"
            raise CninfoFullDiscoveryError(detail)
        for audit in shard.audits:
            if audit.audit_version != "cninfo_listing_discovery_v1":
                detail = "unsupported discovery observation version"
                raise CninfoFullDiscoveryError(detail)
            if _audit_identity(audit) != audit.audit_id:
                detail = "discovery observation hash differs"
                raise CninfoFullDiscoveryError(detail)
    missing_indices = tuple(index for index in range(len(plan.shards)) if index not in indices)
    selected = sum(shard.selected_count for shard in ordered)
    missing = sum(shard.missing_count for shard in ordered)
    failures = tuple(
        DiscoveryFailure(
            symbol=audit.candidate.symbol, audit_id=audit.audit_id, reason=audit.failure_reason
        )
        for shard in ordered
        for audit in shard.audits
        if audit.failure_reason is not None
    )
    draft = CninfoDiscoveryCoverage(
        report_id="",
        report_version="cninfo_discovery_coverage_v1",
        selection_id=selection.selection_id,
        plan_id=plan.plan_id,
        shard_ids=tuple(shard.shard_id for shard in ordered),
        candidate_universe_sha256=selection.candidate_universe_sha256,
        candidate_count=plan.candidate_count,
        observed_count=selected + missing,
        unobserved_count=plan.candidate_count - selected - missing,
        selected_count=selected,
        missing_count=missing,
        missing_shard_indices=missing_indices,
        failures=failures,
        status="INCOMPLETE_DISCOVERY" if missing_indices else "COMPLETE_DISCOVERY",
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"report_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return draft.model_copy(
        update={
            "report_id": "cninfo_discovery_coverage_" + hashlib.sha256(payload.encode()).hexdigest()
        }
    )


def _audit_identity(audit: CninfoListingDiscoveryAudit) -> str:
    payload = json.dumps(
        audit.model_dump(mode="json", exclude={"audit_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "cninfo_listing_discovery_" + hashlib.sha256(payload.encode()).hexdigest()
