"""Typed contracts for governed weekly financial-factor orchestration."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from ashare_lab.research.artifacts import ArtifactDescriptor
from ashare_lab.research.features.financial.materialization import (
    FinancialFeatureMaterializationRequest,
)
from ashare_lab.research.features.financial.models import FinancialIndicatorObservation


class FinancialFeatureEvidenceReader(Protocol):
    """Read-only accepted PIT financial-version capability."""

    def read(
        self,
        end_time: datetime,
        schema_manifest_id: str,
    ) -> tuple[FinancialIndicatorObservation, ...]:
        """Load accepted versions visible by the inclusive upper cutoff."""
        ...


@unique
class FinancialFeatureServiceRule(StrEnum):
    """Stable orchestration failures that forbid artifact publication."""

    UNIVERSE_IDENTITY_MISMATCH = "universe_identity_mismatch"
    INVALID_UNIVERSE_EVIDENCE = "invalid_universe_evidence"
    DIRTY_WORKTREE = "dirty_worktree"


class FinancialFeatureServiceError(Exception):
    """The declared financial run is inconsistent with immutable evidence."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: FinancialFeatureServiceRule, detail: str) -> None:
        """Create a stable fail-closed service error."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable rule and concrete identity detail."""
        return f"{self.rule.value}: {self.detail}"


class FinancialUniverseKey(BaseModel):
    """Parsed universe key and its latest visible evidence clock."""

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
class FinancialFeatureRunRequest:
    """Closed interval and immutable upstream identities for one factor run."""

    start_date: date
    end_date: date
    financial_schema_manifest_id: str
    universe_artifact: ArtifactDescriptor
    materialization: FinancialFeatureMaterializationRequest


@dataclass(frozen=True, slots=True)
class FinancialFeatureMaterializationResult:
    """Published artifacts and explicit completeness counters."""

    artifacts: tuple[ArtifactDescriptor, ...]
    decision_count: int
    universe_key_count: int
    row_count: int
    financial_version_count: int
