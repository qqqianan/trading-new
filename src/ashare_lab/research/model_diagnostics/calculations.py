"""Post-hoc Ridge diagnostics over immutable development artifacts."""

from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import polars as pl
from pydantic import TypeAdapter

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.research.model_diagnostics.models import (
    CoefficientStability,
    ModelDiagnosticReport,
    RankIcSegment,
)
from ashare_lab.research.model_diagnostics.portfolio import (
    PortfolioComparisonInput,
    portfolio_comparison,
)

_MINIMUM_PAIRS: Final = 5
_DATE = TypeAdapter(date)
_FLOAT = TypeAdapter(float)


class ModelDiagnosticError(Exception):
    """Development artifacts cannot form one honest model diagnosis."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable diagnostic blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the diagnostic boundary and concrete blocker."""
        return f"model_diagnostic: {self.detail}"


@dataclass(frozen=True, slots=True)
class ModelDiagnosticInput:
    """Exact artifacts admitted to one post-hoc report."""

    model: RidgeExperimentArtifact
    predictions: pl.DataFrame
    baseline_targets: PortfolioTargetBatch
    model_targets: PortfolioTargetBatch
    baseline_backtest_id: str
    baseline_backtest: PortfolioBacktestReport
    model_backtest_id: str
    model_backtest: PortfolioBacktestReport


def diagnose_ridge_model(request: ModelDiagnosticInput) -> ModelDiagnosticReport:
    """Describe Ridge behavior without selecting parameters or opening holdout data."""
    _validate_input(request)
    daily = _daily_rank_ic(request.predictions)
    folds = tuple(
        _segment(str(fold), daily.filter(pl.col("fold_index") == fold))
        for fold in sorted(daily["fold_index"].unique().to_list())
    )
    years = tuple(
        _segment(str(year), daily.filter(pl.col("year") == year))
        for year in sorted(daily["year"].unique().to_list())
    )
    model = request.model
    return ModelDiagnosticReport(
        model_id=model.model_id,
        dataset_snapshot_id=model.dataset_snapshot_id,
        prediction_artifact_sha256=model.prediction_artifact_sha256,
        factor_report_id=_required_factor_report(model),
        selected_alpha=model.selected_alpha,
        prediction_rows=request.predictions.height,
        overall_rank_ic=_segment("ALL", daily),
        fold_segments=folds,
        yearly_segments=years,
        coefficient_stability=_coefficient_stability(model),
        portfolio=portfolio_comparison(
            PortfolioComparisonInput(
                request.baseline_backtest_id,
                request.baseline_backtest,
                request.model_backtest_id,
                request.model_backtest,
                request.baseline_targets,
                request.model_targets,
            )
        ),
        industry_neutralization="UNAVAILABLE",
        diagnostic_scope="POST_HOC_DEVELOPMENT_ONLY",
        tuning_permitted=False,
        model_status="DRAFT",
        final_test_runs=0,
    )


def _validate_input(request: ModelDiagnosticInput) -> None:
    model = request.model
    frame = request.predictions
    expected = ["decision_time", "symbol", "fold_index", "model_score", "label_value"]
    if frame.columns != expected or frame.is_empty():
        detail = "prediction evaluation frame is empty or has unexpected columns"
        raise ModelDiagnosticError(detail)
    if (
        not frame.select(pl.col("model_score").is_finite().all()).item()
        or not frame.select(pl.col("label_value").is_finite().all()).item()
    ):
        detail = "prediction evaluation values must be finite"
        raise ModelDiagnosticError(detail)
    latest = _DATE.validate_python(frame["decision_time"].dt.date().max())
    if latest > date(2024, 12, 31):
        detail = "prediction evaluation frame contains final holdout rows"
        raise ModelDiagnosticError(detail)
    backtests = (request.baseline_backtest, request.model_backtest)
    targets = (request.baseline_targets, request.model_targets)
    if (
        model.model_status != "DRAFT"
        or model.final_test_runs != 0
        or model.prediction_row_count != frame.height
        or any(item.final_test_runs != 0 for item in backtests)
        or any(item.dataset_snapshot_id != model.dataset_snapshot_id for item in backtests)
        or any(item.dataset_snapshot_id != model.dataset_snapshot_id for item in targets)
        or request.baseline_backtest.model_id is not None
        or request.baseline_targets.model_id is not None
        or request.model_backtest.model_id != model.model_id
        or request.model_targets.model_id != model.model_id
    ):
        detail = "model, targets, backtests, or holdout identities differ"
        raise ModelDiagnosticError(detail)
    fold_indexes = tuple(item.fold_index for item in model.fold_results)
    prediction_folds = tuple(sorted(frame["fold_index"].unique().to_list()))
    if (
        len(set(fold_indexes)) != len(fold_indexes)
        or tuple(sorted(fold_indexes)) != prediction_folds
    ):
        detail = "model fold evidence differs from prediction batches"
        raise ModelDiagnosticError(detail)
    _verify_fold_mse(model, frame)


def _daily_rank_ic(frame: pl.DataFrame) -> pl.DataFrame:
    ranked = frame.with_columns(
        pl.col("model_score").rank("average").over("decision_time").alias("score_rank"),
        pl.col("label_value").rank("average").over("decision_time").alias("label_rank"),
    )
    daily = (
        ranked.group_by("decision_time")
        .agg(
            pl.first("fold_index").alias("fold_index"),
            pl.col("fold_index").n_unique().alias("fold_count"),
            pl.len().alias("observations"),
            pl.corr("score_rank", "label_rank").alias("rank_ic"),
        )
        .filter((pl.col("observations") >= _MINIMUM_PAIRS) & pl.col("rank_ic").is_finite())
        .with_columns(pl.col("decision_time").dt.year().alias("year"))
        .sort("decision_time")
    )
    if daily.is_empty() or daily["fold_count"].max() != 1:
        detail = "decision dates lack valid Rank IC or cross fold boundaries"
        raise ModelDiagnosticError(detail)
    return daily


def _segment(name: str, daily: pl.DataFrame) -> RankIcSegment:
    values = daily["rank_ic"].to_numpy()
    mean = float(np.mean(values))
    standard_deviation = float(np.std(values, ddof=0))
    return RankIcSegment(
        segment=name,
        decision_dates=daily.height,
        observations=int(daily["observations"].sum()),
        mean_rank_ic=mean,
        icir=0.0 if standard_deviation == 0 else mean / standard_deviation,
        direction_consistency=float(np.mean(values > 0)),
    )


def _verify_fold_mse(model: RidgeExperimentArtifact, frame: pl.DataFrame) -> None:
    for fold in model.fold_results:
        rows = frame.filter(pl.col("fold_index") == fold.fold_index)
        mse = _FLOAT.validate_python(((rows["label_value"] - rows["model_score"]) ** 2).mean())
        if not np.isclose(mse, fold.internal_test_mse, rtol=1e-12, atol=1e-15):
            detail = f"prediction loss differs from fold {fold.fold_index} manifest"
            raise ModelDiagnosticError(detail)


def _coefficient_stability(
    model: RidgeExperimentArtifact,
) -> tuple[CoefficientStability, ...]:
    expected = len(model.model_feature_names)
    rows = tuple(item.coefficients for item in model.fold_results)
    if not rows or any(len(row) != expected for row in rows):
        detail = "per-fold coefficient evidence is absent or incomplete"
        raise ModelDiagnosticError(detail)
    matrix = np.asarray(rows, dtype=np.float64)
    return tuple(
        CoefficientStability(
            feature_name=name,
            mean=float(np.mean(values)),
            standard_deviation=float(np.std(values, ddof=0)),
            sign_consistency=float(
                max(
                    np.count_nonzero(values > 0),
                    np.count_nonzero(values < 0),
                    np.count_nonzero(values == 0),
                )
                / len(values)
            ),
        )
        for name, values in zip(model.model_feature_names, matrix.T, strict=True)
    )


def _required_factor_report(model: RidgeExperimentArtifact) -> str:
    if model.factor_report_id is None:
        detail = "model factor report lineage is absent"
        raise ModelDiagnosticError(detail)
    return model.factor_report_id
