"""Deterministic stratified sampling for the CNInfo source-audit pilot."""

import hashlib
import json
from collections import defaultdict
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.official_bridge_candidates import (
    OfficialBridgeCandidate,
    candidate_universe_sha256,
)

SELECTION_VERSION: Final = "cninfo_bridge_pilot_v1"


class CandidateStratum(BaseModel):
    """Population and fixed quota for one year-exchange stratum."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    listing_year: int
    exchange: str = Field(pattern=r"^(SZ|SH|BJ)$")
    population: int = Field(gt=0)
    quota: int = Field(gt=0)


class StratifiedCandidateSelection(BaseModel):
    """Stable pilot selection bound to the complete candidate universe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selection_id: str = Field(pattern=r"^cninfo_bridge_selection_[0-9a-f]{64}$")
    selection_version: str
    candidate_universe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_count: int = Field(gt=0)
    sample_size: int = Field(gt=0)
    strata: tuple[CandidateStratum, ...]
    selected: tuple[OfficialBridgeCandidate, ...]


class CandidateSelectionError(Exception):
    """The requested sample cannot satisfy the fixed stratification protocol."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record a deterministic protocol failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the protocol boundary and failure detail."""
        return f"cninfo_bridge_sampling: {self.detail}"


def select_stratified_candidates(
    candidates: tuple[OfficialBridgeCandidate, ...],
    *,
    sample_size: int,
) -> StratifiedCandidateSelection:
    """Select every stratum once, then allocate remaining seats by largest remainder."""
    if len({item.symbol for item in candidates}) != len(candidates):
        detail = "candidate symbols must be unique"
        raise CandidateSelectionError(detail)
    groups: dict[tuple[int, str], list[OfficialBridgeCandidate]] = defaultdict(list)
    for candidate in candidates:
        groups[(candidate.listing_date.year, candidate.exchange)].append(candidate)
    if sample_size < len(groups) or sample_size > len(candidates):
        detail = "sample size cannot cover all strata within population"
        raise CandidateSelectionError(detail)
    quotas = _allocate_quotas(groups, sample_size)
    selected: list[OfficialBridgeCandidate] = []
    strata: list[CandidateStratum] = []
    for key in sorted(groups):
        population = groups[key]
        quota = quotas[key]
        ranked = sorted(population, key=_selection_key)
        selected.extend(ranked[:quota])
        strata.append(
            CandidateStratum(
                listing_year=key[0],
                exchange=key[1],
                population=len(population),
                quota=quota,
            )
        )
    draft = StratifiedCandidateSelection(
        selection_id=f"cninfo_bridge_selection_{'0' * 64}",
        selection_version=SELECTION_VERSION,
        candidate_universe_sha256=candidate_universe_sha256(candidates),
        candidate_count=len(candidates),
        sample_size=sample_size,
        strata=tuple(strata),
        selected=tuple(selected),
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"selection_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"selection_id": f"cninfo_bridge_selection_{digest}"})


def _allocate_quotas(
    groups: dict[tuple[int, str], list[OfficialBridgeCandidate]],
    sample_size: int,
) -> dict[tuple[int, str], int]:
    remaining = sample_size - len(groups)
    population = sum(len(items) for items in groups.values())
    quotas = dict.fromkeys(groups, 1)
    floors: dict[tuple[int, str], int] = {}
    remainders: list[tuple[int, tuple[int, str]]] = []
    for key, items in groups.items():
        numerator = remaining * len(items)
        floor, remainder = divmod(numerator, population)
        floors[key] = floor
        remainders.append((remainder, key))
    for key, floor in floors.items():
        quotas[key] += floor
    seats = remaining - sum(floors.values())
    for _remainder, key in sorted(remainders, key=lambda item: (-item[0], item[1]))[:seats]:
        quotas[key] += 1
    return quotas


def _selection_key(candidate: OfficialBridgeCandidate) -> tuple[str, str]:
    payload = (
        f"{SELECTION_VERSION}|{candidate.symbol}|{candidate.listing_date.isoformat()}".encode()
    )
    return hashlib.sha256(payload).hexdigest(), candidate.symbol
