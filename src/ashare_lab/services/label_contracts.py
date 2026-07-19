"""Typed contracts for governed future-label orchestration."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from ashare_lab.research.artifacts import ArtifactDescriptor
from ashare_lab.research.labels.materialization import LabelMaterializationRequest
from ashare_lab.research.labels.models import BenchmarkOpenObservation, LabelTradeObservation


class LabelEvidenceReader(Protocol):
    """Read-only calendar, stock execution, and benchmark-open capability."""

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        """Load governed open sessions over one closed interval."""
        ...

    def stock_observations(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[LabelTradeObservation, ...]:
        """Load stock open and fixed-session execution evidence."""
        ...

    def benchmark_observations(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        schema_manifest_id: str,
    ) -> tuple[BenchmarkOpenObservation, ...]:
        """Load one benchmark's raw opens over one closed interval."""
        ...


@unique
class LabelServiceRule(StrEnum):
    """Stable orchestration failures that forbid label publication."""

    UNIVERSE_IDENTITY_MISMATCH = "universe_identity_mismatch"
    INVALID_UNIVERSE_EVIDENCE = "invalid_universe_evidence"
    INVALID_CALENDAR_EVIDENCE = "invalid_calendar_evidence"
    DUPLICATE_SOURCE_EVIDENCE = "duplicate_source_evidence"
    DIRTY_WORKTREE = "dirty_worktree"


class LabelServiceError(Exception):
    """The declared label run is inconsistent with immutable evidence."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: LabelServiceRule, detail: str) -> None:
        """Create a stable fail-closed service error."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable rule and concrete evidence detail."""
        return f"{self.rule.value}: {self.detail}"


class LabelUniverseKey(BaseModel):
    """Parsed immutable universe key and its point-in-time clock."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    symbol: str
    decision_time: datetime
    available_at: datetime

    @model_validator(mode="after")
    def validate_pit_clocks(self) -> Self:
        """Require universe evidence available by the decision clock."""
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.decision_time, self.available_at)
        ):
            detail = "universe clocks must be timezone-aware"
            raise ValueError(detail)
        if self.available_at > self.decision_time:
            detail = "universe available_at exceeds decision_time"
            raise ValueError(detail)
        return self


@dataclass(frozen=True, slots=True)
class LabelRunRequest:
    """Decision interval, evidence cutoff, and immutable input identities."""

    start_date: date
    end_date: date
    evidence_end_date: date
    market_schema_manifest_id: str
    benchmark_schema_manifest_id: str
    universe_artifact: ArtifactDescriptor
    materialization: LabelMaterializationRequest


@dataclass(frozen=True, slots=True)
class LabelMaterializationResult:
    """Published target artifact and explicit completeness counters."""

    artifact: ArtifactDescriptor
    decision_count: int
    universe_key_count: int
    row_count: int
