"""Post-hoc portfolio attribution over immutable development artifacts."""

from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import polars as pl
from pydantic import TypeAdapter

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.research.model_attribution.models import (
    ModelPerformanceAttributionReport,
    TailReturnAttribution,
)
from ashare_lab.research.model_attribution.portfolio import (
    annual_performance,
    risk_constraints,
)

_EXPECTED_COLUMNS: Final = (
    "decision_time",
    "symbol",
    "fold_index",
    "model_score",
    "label_value",
)
_DATE = TypeAdapter(date)


class ModelAttributionError(Exception):
    """Frozen development evidence cannot form one honest attribution."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable attribution blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the attribution boundary and concrete blocker."""
        return f"model_attribution: {self.detail}"


@dataclass(frozen=True, slots=True)
class ModelAttributionInput:
    """Exact artifacts admitted to one development-only attribution."""

    diagnostic_report_id: str
    model: RidgeExperimentArtifact
    predictions: pl.DataFrame
    model_targets: PortfolioTargetBatch
    baseline_backtest_id: str
    baseline_backtest: PortfolioBacktestReport
    model_backtest_id: str
    model_backtest: PortfolioBacktestReport


def attribute_model_portfolio(
    request: ModelAttributionInput,
) -> ModelPerformanceAttributionReport:
    """Attribute frozen signal tails and execution without fitting a model."""
    _validate_evidence(request)
    daily = _daily_tail_returns(request.predictions, request.model_targets)
    years = sorted(daily["year"].unique().to_list())
    model = request.model
    return ModelPerformanceAttributionReport(
        diagnostic_report_id=request.diagnostic_report_id,
        model_id=model.model_id,
        dataset_snapshot_id=model.dataset_snapshot_id,
        prediction_artifact_sha256=model.prediction_artifact_sha256,
        model_target_artifact_id=request.model_backtest.target_artifact_id,
        baseline_backtest_id=request.baseline_backtest_id,
        model_backtest_id=request.model_backtest_id,
        overall_tail=_tail_segment("ALL", daily),
        yearly_tail=tuple(
            _tail_segment(str(year), daily.filter(pl.col("year") == year)) for year in years
        ),
        annual_performance=annual_performance(
            request.baseline_backtest,
            request.model_backtest,
        ),
        execution_constraints=(
            *risk_constraints("BASELINE", request.baseline_backtest),
            *risk_constraints("MODEL", request.model_backtest),
        ),
        baseline_pending_orders=request.baseline_backtest.metrics.pending_order_count,
        model_pending_orders=request.model_backtest.metrics.pending_order_count,
        baseline_risk_event_count=len(request.baseline_backtest.result.risk_events),
        model_risk_event_count=len(request.model_backtest.result.risk_events),
        label_semantics="raw_forward_return_for_diagnostics",
        diagnostic_scope="POST_HOC_DEVELOPMENT_ATTRIBUTION_ONLY",
        tuning_permitted=False,
        model_status="DRAFT",
        final_test_runs=0,
    )


def _validate_evidence(request: ModelAttributionInput) -> None:
    model = request.model
    frame = request.predictions
    targets = request.model_targets
    backtests = (request.baseline_backtest, request.model_backtest)
    if tuple(frame.columns) != _EXPECTED_COLUMNS or frame.is_empty():
        detail = "prediction frame is empty or has unexpected columns"
        raise ModelAttributionError(detail)
    if (
        not frame.select(pl.col("model_score").is_finite().all()).item()
        or not frame.select(pl.col("label_value").is_finite().all()).item()
    ):
        detail = "prediction values must be finite"
        raise ModelAttributionError(detail)
    latest = _DATE.validate_python(frame["decision_time"].dt.date().max())
    if latest > date(2024, 12, 31):
        detail = "prediction frame contains final holdout rows"
        raise ModelAttributionError(detail)
    if (
        model.model_status != "DRAFT"
        or model.final_test_runs != 0
        or model.prediction_row_count != frame.height
        or targets.model_id != model.model_id
        or targets.dataset_snapshot_id != model.dataset_snapshot_id
        or any(item.dataset_snapshot_id != model.dataset_snapshot_id for item in backtests)
        or any(item.final_test_runs != 0 for item in backtests)
        or request.baseline_backtest.model_id is not None
        or request.model_backtest.model_id != model.model_id
    ):
        detail = "model, targets, backtests, or holdout identities differ"
        raise ModelAttributionError(detail)


def _daily_tail_returns(
    predictions: pl.DataFrame,
    targets: PortfolioTargetBatch,
) -> pl.DataFrame:
    target_rows = tuple(
        (record.decision_date, position.symbol)
        for record in targets.records
        for position in record.positions
    )
    keys = pl.DataFrame(
        target_rows,
        schema={"decision_date": pl.Date, "symbol": pl.String},
        orient="row",
    ).with_columns(pl.lit(value=True).alias("selected"))
    if keys.is_duplicated().any():
        detail = "target keys are duplicated"
        raise ModelAttributionError(detail)
    frame = predictions.with_columns(pl.col("decision_time").dt.date().alias("decision_date"))
    prediction_dates = set(frame["decision_date"].to_list())
    target_dates = set(keys["decision_date"].to_list())
    if prediction_dates != target_dates:
        detail = "target keys do not cover exact prediction dates"
        raise ModelAttributionError(detail)
    counts = keys.group_by("decision_date").len().rename({"len": "selected_count"})
    joined = (
        frame.join(keys, on=["decision_date", "symbol"], how="left")
        .join(counts, on="decision_date", how="left")
        .with_columns(
            pl.col("selected").fill_null(value=False),
            pl.col("model_score").rank("ordinal").over("decision_date").alias("bottom_rank"),
        )
    )
    if int(joined["selected"].sum()) != keys.height:
        detail = "target keys are absent from prediction evidence"
        raise ModelAttributionError(detail)
    return (
        joined.group_by("decision_date")
        .agg(
            pl.len().alias("universe_observations"),
            pl.col("selected").sum().alias("selected_observations"),
            pl.col("label_value").mean().alias("universe_return"),
            pl.col("label_value").filter(pl.col("selected")).mean().alias("selected_return"),
            pl.col("label_value")
            .filter(pl.col("bottom_rank") <= pl.col("selected_count"))
            .mean()
            .alias("bottom_return"),
        )
        .with_columns(pl.col("decision_date").dt.year().alias("year"))
        .sort("decision_date")
    )


def _tail_segment(name: str, daily: pl.DataFrame) -> TailReturnAttribution:
    universe = daily["universe_return"].to_numpy()
    selected = daily["selected_return"].to_numpy()
    bottom = daily["bottom_return"].to_numpy()
    return TailReturnAttribution(
        segment=name,
        decision_dates=daily.height,
        universe_observations=int(daily["universe_observations"].sum()),
        selected_observations=int(daily["selected_observations"].sum()),
        mean_universe_label_return=float(np.mean(universe)),
        mean_selected_label_return=float(np.mean(selected)),
        mean_bottom_label_return=float(np.mean(bottom)),
        selected_excess_vs_universe=float(np.mean(selected - universe)),
        selected_minus_bottom=float(np.mean(selected - bottom)),
        selected_daily_win_rate=float(np.mean(selected > universe)),
    )
