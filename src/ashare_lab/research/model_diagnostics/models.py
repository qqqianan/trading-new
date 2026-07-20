"""Immutable model diagnostic report contracts."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ashare_lab.research.factors.models import stable_metric


class FrozenDiagnosticModel(BaseModel):
    """Strict immutable boundary for post-hoc diagnostic evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RankIcSegment(FrozenDiagnosticModel):
    """Cross-sectional prediction Rank IC summarized over one fixed segment."""

    segment: str = Field(min_length=1)
    decision_dates: int = Field(gt=0)
    observations: int = Field(gt=0)
    mean_rank_ic: float = Field(allow_inf_nan=False)
    icir: float = Field(allow_inf_nan=False)
    direction_consistency: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("mean_rank_ic", "icir", "direction_consistency")
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze scalar precision before report hashing."""
        return stable_metric(value)


class CoefficientStability(FrozenDiagnosticModel):
    """One model feature's coefficient behavior across fitted folds."""

    feature_name: str = Field(min_length=1)
    mean: float = Field(allow_inf_nan=False)
    standard_deviation: float = Field(ge=0, allow_inf_nan=False)
    sign_consistency: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("mean", "standard_deviation", "sign_consistency")
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze scalar precision before report hashing."""
        return stable_metric(value)


class BacktestComparison(FrozenDiagnosticModel):
    """Like-for-like governed portfolio evidence for baseline and model."""

    baseline_backtest_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    model_backtest_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    baseline_total_return: float = Field(allow_inf_nan=False)
    model_total_return: float = Field(allow_inf_nan=False)
    baseline_annualized_return: float = Field(allow_inf_nan=False)
    model_annualized_return: float = Field(allow_inf_nan=False)
    baseline_sharpe: float = Field(allow_inf_nan=False)
    model_sharpe: float = Field(allow_inf_nan=False)
    baseline_max_drawdown: float = Field(ge=-1, le=0, allow_inf_nan=False)
    model_max_drawdown: float = Field(ge=-1, le=0, allow_inf_nan=False)
    baseline_turnover: float = Field(ge=0, allow_inf_nan=False)
    model_turnover: float = Field(ge=0, allow_inf_nan=False)
    baseline_fees: float = Field(ge=0, allow_inf_nan=False)
    model_fees: float = Field(ge=0, allow_inf_nan=False)
    baseline_pending_orders: int = Field(ge=0)
    model_pending_orders: int = Field(ge=0)
    baseline_trades: int = Field(ge=0)
    model_trades: int = Field(ge=0)
    mean_top30_overlap: float = Field(ge=0, le=1, allow_inf_nan=False)
    minimum_top30_overlap: float = Field(ge=0, le=1, allow_inf_nan=False)
    risk_halt_date: date | None
    risk_halt_rule: str | None

    @field_validator(
        "baseline_total_return",
        "model_total_return",
        "baseline_annualized_return",
        "model_annualized_return",
        "baseline_sharpe",
        "model_sharpe",
        "baseline_max_drawdown",
        "model_max_drawdown",
        "baseline_turnover",
        "model_turnover",
        "baseline_fees",
        "model_fees",
        "mean_top30_overlap",
        "minimum_top30_overlap",
    )
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze persisted portfolio comparisons before hashing."""
        return stable_metric(value)


class ModelDiagnosticReport(FrozenDiagnosticModel):
    """Complete post-hoc development evidence that cannot authorize tuning."""

    model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    prediction_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    factor_report_id: str = Field(pattern=r"^factor_report_[0-9a-f]{64}$")
    selected_alpha: float = Field(gt=0, allow_inf_nan=False)
    prediction_rows: int = Field(gt=0)
    overall_rank_ic: RankIcSegment
    fold_segments: tuple[RankIcSegment, ...] = Field(min_length=1)
    yearly_segments: tuple[RankIcSegment, ...] = Field(min_length=1)
    coefficient_stability: tuple[CoefficientStability, ...] = Field(min_length=1)
    portfolio: BacktestComparison
    industry_neutralization: Literal["UNAVAILABLE"]
    diagnostic_scope: Literal["POST_HOC_DEVELOPMENT_ONLY"]
    tuning_permitted: Literal[False]
    model_status: Literal["DRAFT"]
    final_test_runs: Literal[0]
