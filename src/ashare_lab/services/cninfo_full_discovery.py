"""Frozen full-population selection and recoverable CNInfo discovery shards."""

import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.data.cninfo_listing_discovery import (
    CninfoDiscoveryStatus,
    CninfoListingDiscoveryAudit,
)
from ashare_lab.data.official_bridge_candidates import (
    OfficialBridgeCandidate,
    candidate_universe_sha256,
)
from ashare_lab.services.cninfo_bridge_sampling import (
    CandidateStratum,
    StratifiedCandidateSelection,
)

_SELECTION_VERSION: Final = "cninfo_bridge_full_population_v1"
_PLAN_VERSION: Final = "cninfo_full_discovery_plan_v1"
_SHARD_VERSION: Final = "cninfo_full_discovery_shard_v1"
_EXPECTED_CANDIDATES: Final = 842


class CninfoDiscoveryShardSpec(BaseModel):
    """One immutable offset range in the full ordered population."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shard_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset_exclusive: int = Field(gt=0)
    candidate_keys_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CninfoFullDiscoveryPlan(BaseModel):
    """Content-addressed shard plan created before provider requests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str = Field(pattern=r"^cninfo_full_discovery_plan_[0-9a-f]{64}$")
    plan_version: str
    planned_at: datetime
    selection_id: str = Field(pattern=r"^cninfo_bridge_selection_[0-9a-f]{64}$")
    candidate_universe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_count: int = Field(gt=0)
    shard_size: int = Field(gt=0)
    shards: tuple[CninfoDiscoveryShardSpec, ...] = Field(min_length=1)
    research_use_authorized: bool


class CninfoFullDiscoveryShard(BaseModel):
    """One exact completed shard retaining every discovery outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shard_id: str = Field(pattern=r"^cninfo_full_discovery_shard_[0-9a-f]{64}$")
    shard_version: str
    plan_id: str = Field(pattern=r"^cninfo_full_discovery_plan_[0-9a-f]{64}$")
    selection_id: str = Field(pattern=r"^cninfo_bridge_selection_[0-9a-f]{64}$")
    shard_index: int = Field(ge=0)
    completed_at: datetime
    audits: tuple[CninfoListingDiscoveryAudit, ...] = Field(min_length=1)
    selected_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    research_use_authorized: bool

    @model_validator(mode="after")
    def counts_match(self) -> Self:
        """Prevent serialized shards from hiding failures or enabling research use."""
        if self.selected_count + self.missing_count != len(self.audits):
            message = "discovery shard counts differ from audits"
            raise ValueError(message)
        if self.research_use_authorized:
            message = "discovery shard cannot authorize research use"
            raise ValueError(message)
        return self


class CninfoFullDiscoveryError(Exception):
    """Full selection, plan, or shard evidence differs from its exact parent."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record a stable full-discovery blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the full-discovery boundary and reason."""
        return f"cninfo_full_discovery: {self.detail}"


def freeze_full_candidate_selection(
    candidates: tuple[OfficialBridgeCandidate, ...],
) -> StratifiedCandidateSelection:
    """Freeze every candidate exactly once in stable symbol order."""
    ordered = tuple(sorted(candidates, key=lambda item: item.symbol))
    if len({item.symbol for item in ordered}) != len(ordered):
        detail = "candidate symbols must be unique"
        raise CninfoFullDiscoveryError(detail)
    counts = Counter((item.listing_date.year, item.exchange) for item in ordered)
    strata = tuple(
        CandidateStratum(listing_year=year, exchange=exchange, population=count, quota=count)
        for (year, exchange), count in sorted(counts.items())
    )
    draft = StratifiedCandidateSelection(
        selection_id=f"cninfo_bridge_selection_{'0' * 64}",
        selection_version=_SELECTION_VERSION,
        candidate_universe_sha256=candidate_universe_sha256(ordered),
        candidate_count=len(ordered),
        sample_size=len(ordered),
        strata=strata,
        selected=ordered,
    )
    digest = _digest(
        json.dumps(
            draft.model_dump(mode="json", exclude={"selection_id"}),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return draft.model_copy(update={"selection_id": f"cninfo_bridge_selection_{digest}"})


def build_full_discovery_plan(
    selection: StratifiedCandidateSelection,
    *,
    shard_size: int,
    planned_at: datetime,
) -> CninfoFullDiscoveryPlan:
    """Partition a complete frozen selection without observing provider outcomes."""
    if (
        selection.sample_size != selection.candidate_count
        or selection.candidate_count != _EXPECTED_CANDIDATES
        or shard_size <= 0
    ):
        detail = "plan requires the exact 842-candidate population and positive shard size"
        raise CninfoFullDiscoveryError(detail)
    shards = tuple(
        CninfoDiscoveryShardSpec(
            shard_index=index // shard_size,
            start_offset=index,
            end_offset_exclusive=min(index + shard_size, selection.candidate_count),
            candidate_keys_sha256=_candidate_keys_digest(
                selection.selected[index : index + shard_size]
            ),
        )
        for index in range(0, selection.candidate_count, shard_size)
    )
    draft = CninfoFullDiscoveryPlan(
        plan_id=f"cninfo_full_discovery_plan_{'0' * 64}",
        plan_version=_PLAN_VERSION,
        planned_at=planned_at,
        selection_id=selection.selection_id,
        candidate_universe_sha256=selection.candidate_universe_sha256,
        candidate_count=selection.candidate_count,
        shard_size=shard_size,
        shards=shards,
        research_use_authorized=False,
    )
    digest = _digest(
        json.dumps(
            draft.model_dump(mode="json", exclude={"plan_id"}),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return draft.model_copy(update={"plan_id": f"cninfo_full_discovery_plan_{digest}"})


def build_full_discovery_shard(
    plan: CninfoFullDiscoveryPlan,
    selection: StratifiedCandidateSelection,
    *,
    shard_index: int,
    audits: tuple[CninfoListingDiscoveryAudit, ...],
    completed_at: datetime,
) -> CninfoFullDiscoveryShard:
    """Bind ordered discovery audits to one exact planned shard."""
    linked = (
        plan.selection_id == selection.selection_id
        and plan.candidate_universe_sha256 == selection.candidate_universe_sha256
        and plan.candidate_count == selection.candidate_count == _EXPECTED_CANDIDATES
        and selection.sample_size == selection.candidate_count
        and not plan.research_use_authorized
    )
    if not linked:
        detail = "plan and selection evidence differ"
        raise CninfoFullDiscoveryError(detail)
    if shard_index >= len(plan.shards):
        detail = "shard index is outside the plan"
        raise CninfoFullDiscoveryError(detail)
    spec = plan.shards[shard_index]
    expected = selection.selected[spec.start_offset : spec.end_offset_exclusive]
    observed_keys = tuple((item.candidate.symbol, item.candidate.listing_date) for item in audits)
    expected_keys = tuple((item.symbol, item.listing_date) for item in expected)
    valid = (
        observed_keys == expected_keys
        and _candidate_keys_digest(expected) == spec.candidate_keys_sha256
        and not any(item.research_use_authorized for item in audits)
    )
    if not valid:
        detail = "audit keys or authority differ from planned shard"
        raise CninfoFullDiscoveryError(detail)
    selected_count = sum(item.status is CninfoDiscoveryStatus.SELECTED for item in audits)
    draft = CninfoFullDiscoveryShard(
        shard_id=f"cninfo_full_discovery_shard_{'0' * 64}",
        shard_version=_SHARD_VERSION,
        plan_id=plan.plan_id,
        selection_id=selection.selection_id,
        shard_index=shard_index,
        completed_at=completed_at,
        audits=audits,
        selected_count=selected_count,
        missing_count=len(audits) - selected_count,
        research_use_authorized=False,
    )
    digest = _digest(
        json.dumps(
            draft.model_dump(mode="json", exclude={"shard_id"}),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return draft.model_copy(update={"shard_id": f"cninfo_full_discovery_shard_{digest}"})


def _candidate_keys_digest(candidates: tuple[OfficialBridgeCandidate, ...]) -> str:
    keys = tuple((item.symbol, item.listing_date.isoformat()) for item in candidates)
    return _digest(json.dumps(keys, ensure_ascii=True, separators=(",", ":")))


def _digest(serialized: str) -> str:
    return hashlib.sha256(serialized.encode()).hexdigest()
