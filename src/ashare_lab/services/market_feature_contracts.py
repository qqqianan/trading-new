"""Typed contracts for governed weekly market-factor orchestration."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from ashare_lab.research.artifacts import ArtifactDescriptor
from ashare_lab.research.features.market.materialization import (
    MarketFeatureMaterializationRequest,
)
from ashare_lab.research.features.market.mongo_contracts import MarketBundleReadResult


class MarketFeatureEvidenceReader(Protocol):
    """Read-only accepted calendar and canonical market bundle capability."""

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        """Load exact accepted open sessions from the governed schema."""
        ...

    def read(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> MarketBundleReadResult:
        """Load complete bundles and explicit rejections for one interval."""
        ...


@unique
class MarketFeatureServiceRule(StrEnum):
    """Stable orchestration failures that forbid artifact publication."""

    UNIVERSE_IDENTITY_MISMATCH = "universe_identity_mismatch"
    INVALID_UNIVERSE_EVIDENCE = "invalid_universe_evidence"
    INVALID_CALENDAR_EVIDENCE = "invalid_calendar_evidence"
    DUPLICATE_MARKET_OBSERVATION = "duplicate_market_observation"
    DIRTY_WORKTREE = "dirty_worktree"


class MarketFeatureServiceError(Exception):
    """The declared factor run is inconsistent with its immutable inputs."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: MarketFeatureServiceRule, detail: str) -> None:
        """Create a stable fail-closed service error."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable rule and concrete identity detail."""
        return f"{self.rule.value}: {self.detail}"


class UniverseFeatureKey(BaseModel):
    """Parsed universe artifact key and its latest visible evidence clock."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    symbol: str
    decision_time: datetime
    available_at: datetime

    @model_validator(mode="after")
    def validate_pit_clocks(self) -> Self:
        """Require timezone-aware evidence visible by the decision clock."""
        clocks = (self.decision_time, self.available_at)
        if any(clock.tzinfo is None or clock.utcoffset() is None for clock in clocks):
            detail = "universe clocks must be timezone-aware"
            raise ValueError(detail)
        if self.available_at > self.decision_time:
            detail = "universe available_at exceeds decision_time"
            raise ValueError(detail)
        return self


@dataclass(frozen=True, slots=True)
class MarketFeatureRunRequest:
    """Closed interval and immutable upstream identities for one factor run."""

    start_date: date
    end_date: date
    market_schema_manifest_id: str
    universe_artifact: ArtifactDescriptor
    materialization: MarketFeatureMaterializationRequest


@dataclass(frozen=True, slots=True)
class MarketFeatureMaterializationResult:
    """Published artifacts and explicit completeness counters."""

    artifacts: tuple[ArtifactDescriptor, ...]
    decision_count: int
    universe_key_count: int
    row_count: int
    bundle_rejection_count: int
