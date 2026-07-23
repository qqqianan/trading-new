"""Immutable contracts for development-only portfolio performance attribution."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ashare_lab.research.factors.models import stable_metric


class FrozenAttributionModel(BaseModel):
    """Strict immutable boundary for post-hoc attribution evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TailReturnAttribution(FrozenAttributionModel):
    """Raw forward-return behavior for one fixed development segment."""

    segment: str = Field(min_length=1)
    decision_dates: int = Field(gt=0)
    universe_observations: int = Field(gt=0)
    selected_observations: int = Field(gt=0)
    mean_universe_label_return: float = Field(allow_inf_nan=False)
    mean_selected_label_return: float = Field(allow_inf_nan=False)
    mean_bottom_label_return: float = Field(allow_inf_nan=False)
    selected_excess_vs_universe: float = Field(allow_inf_nan=False)
    selected_minus_bottom: float = Field(allow_inf_nan=False)
    selected_daily_win_rate: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator(
        "mean_universe_label_return",
        "mean_selected_label_return",
        "mean_bottom_label_return",
        "selected_excess_vs_universe",
        "selected_minus_bottom",
        "selected_daily_win_rate",
    )
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze scalar precision before content hashing."""
        return stable_metric(value)


class AnnualPerformanceAttribution(FrozenAttributionModel):
    """Like-for-like net portfolio performance for one calendar year."""

    year: int = Field(ge=2000, le=2100)
    baseline_return: float = Field(allow_inf_nan=False)
    model_return: float = Field(allow_inf_nan=False)
    return_gap: float = Field(allow_inf_nan=False)
    baseline_excess_return: float = Field(allow_inf_nan=False)
    model_excess_return: float = Field(allow_inf_nan=False)
    excess_return_gap: float = Field(allow_inf_nan=False)

    @field_validator(
        "baseline_return",
        "model_return",
        "return_gap",
        "baseline_excess_return",
        "model_excess_return",
        "excess_return_gap",
    )
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze annual metrics before content hashing."""
        return stable_metric(value)


class ExecutionConstraintAttribution(FrozenAttributionModel):
    """Count of one governed risk action in one compared portfolio."""

    portfolio: Literal["BASELINE", "MODEL"]
    rule: str = Field(min_length=1)
    action: str = Field(min_length=1)
    event_count: int = Field(gt=0)
    affected_symbols: int = Field(ge=0)


class ModelPerformanceAttributionReport(FrozenAttributionModel):
    """Complete development-only attribution that cannot authorize tuning."""

    diagnostic_report_id: str = Field(pattern=r"^model_diagnostic_[0-9a-f]{64}$")
    model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    prediction_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_target_artifact_id: str = Field(pattern=r"^portfolio_targets_[0-9a-f]{64}$")
    baseline_backtest_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    model_backtest_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    overall_tail: TailReturnAttribution
    yearly_tail: tuple[TailReturnAttribution, ...] = Field(min_length=1)
    annual_performance: tuple[AnnualPerformanceAttribution, ...] = Field(min_length=1)
    execution_constraints: tuple[ExecutionConstraintAttribution, ...]
    baseline_pending_orders: int = Field(ge=0)
    model_pending_orders: int = Field(ge=0)
    baseline_risk_event_count: int = Field(ge=0)
    model_risk_event_count: int = Field(ge=0)
    label_semantics: Literal["raw_forward_return_for_diagnostics"]
    diagnostic_scope: Literal["POST_HOC_DEVELOPMENT_ATTRIBUTION_ONLY"]
    tuning_permitted: Literal[False]
    model_status: Literal["DRAFT"]
    final_test_runs: Literal[0]
