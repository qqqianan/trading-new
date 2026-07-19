"""Typed factor hypotheses and complete diagnostic report contracts."""

from enum import StrEnum, unique
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenFactorModel(BaseModel):
    """Immutable model used by factor manifests and report artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


@unique
class ExpectedDirection(StrEnum):
    """Predeclared economic direction applied before diagnostics."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"

    @property
    def multiplier(self) -> float:
        """Return the numeric orientation fixed before labels are inspected."""
        match self:
            case ExpectedDirection.HIGHER_IS_BETTER:
                return 1.0
            case ExpectedDirection.LOWER_IS_BETTER:
                return -1.0


@unique
class FactorFamily(StrEnum):
    """Predefined economic families used for audited redundancy decisions."""

    MOMENTUM = "momentum"
    REVERSAL = "reversal"
    RISK = "risk"
    LIQUIDITY = "liquidity"
    SIZE = "size"
    VALUE = "value"
    QUALITY = "quality"
    GROWTH = "growth"


class FactorHypothesis(FrozenFactorModel):
    """One versioned feature hypothesis declared before diagnostic results."""

    feature_name: str = Field(min_length=1)
    feature_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    family: FactorFamily
    expected_direction: ExpectedDirection
    simplicity_rank: int = Field(ge=0)


class SegmentMetric(FrozenFactorModel):
    """One disclosed segment and its oriented mean rank IC."""

    segment: str = Field(min_length=1)
    observations: int = Field(ge=0)
    mean_rank_ic: float = Field(allow_inf_nan=False)


class FactorDiagnosticReport(FrozenFactorModel):
    """Complete non-selective diagnostics for one registered factor trial."""

    trial_id: str = Field(pattern=r"^factor_trial_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    feature_name: str = Field(min_length=1)
    expected_direction: ExpectedDirection
    total_sample_count: int = Field(gt=0)
    valid_pair_count: int = Field(ge=0)
    missing_feature_count: int = Field(ge=0)
    missing_label_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1, allow_inf_nan=False)
    raw_mean_rank_ic: float = Field(allow_inf_nan=False)
    oriented_mean_rank_ic: float = Field(allow_inf_nan=False)
    icir: float = Field(allow_inf_nan=False)
    direction_consistency: float = Field(ge=0, le=1, allow_inf_nan=False)
    p_value: float = Field(ge=0, le=1, allow_inf_nan=False)
    quintile_mean_labels: tuple[float, float, float, float, float]
    quintile_monotonicity: float = Field(ge=0, le=1, allow_inf_nan=False)
    top_bottom_gross_return: float = Field(allow_inf_nan=False)
    average_turnover: float = Field(ge=0, le=1, allow_inf_nan=False)
    top_bottom_net_return: float = Field(allow_inf_nan=False)
    factor_autocorrelation: float = Field(ge=-1, le=1, allow_inf_nan=False)
    size_exposure: float = Field(ge=-1, le=1, allow_inf_nan=False)
    yearly_segments: tuple[SegmentMetric, ...]
    regime_segments: tuple[SegmentMetric, ...]
    industry_segments: tuple[SegmentMetric, ...]
    worst_year: SegmentMetric | None
    worst_industry: SegmentMetric | None

    @model_validator(mode="after")
    def disclosed_counts_are_consistent(self) -> Self:
        """Reject reports that hide invalid or missing observations."""
        if self.valid_pair_count > self.total_sample_count:
            detail = "valid_pair_count cannot exceed total_sample_count"
            raise ValueError(detail)
        return self
