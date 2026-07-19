"""Complete development-only cross-sectional diagnostics for registered trials."""

from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise
from math import erfc, sqrt
from typing import Final

import polars as pl

from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.factors.diagnostic_segments import (
    average_top_turnover,
    factor_autocorrelation,
    industry_segments,
    regime_segments,
    size_exposure,
    year_segments,
)
from ashare_lab.research.factors.models import FactorDiagnosticReport

_DEVELOPMENT_END: Final = date(2024, 12, 31)
_MINIMUM_CORRELATION_PAIRS: Final = 2


@dataclass(frozen=True, slots=True)
class DiagnosticConfig:
    """Frozen factor metric thresholds and assumed round-trip cost."""

    minimum_pairs_per_date: int = 5
    round_trip_cost_bps: float = 15.0


class FactorDiagnosticError(Exception):
    """A registered factor cannot produce valid development diagnostics."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed diagnostic failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the diagnostic boundary and concrete failure."""
        return f"factor_diagnostic: {self.detail}"


def diagnose_factor(
    frame: pl.DataFrame,
    trial: FactorTrial,
    config: DiagnosticConfig,
) -> FactorDiagnosticReport:
    """Calculate every required metric without selecting or hiding the trial."""
    _validate_input(frame, config)
    valid = frame.filter(
        pl.col("factor_value").is_not_null()
        & pl.col("factor_value").is_finite()
        & pl.col("label_value").is_not_null()
        & pl.col("label_value").is_finite()
    )
    if valid.is_empty():
        detail = "factor has no finite feature-label pairs"
        raise FactorDiagnosticError(detail)
    scored = _ranked_frame(valid, trial.expected_direction.multiplier)
    daily = _daily_rank_ic(scored, config.minimum_pairs_per_date)
    if daily.is_empty():
        detail = "factor has no decision date with enough finite pairs"
        raise FactorDiagnosticError(detail)
    raw_mean = _series_mean(daily["raw_rank_ic"])
    oriented_mean = _series_mean(daily["oriented_rank_ic"])
    standard_deviation = _series_std(daily["oriented_rank_ic"])
    icir = 0.0 if standard_deviation == 0 else oriented_mean / standard_deviation
    standard_error = standard_deviation / sqrt(daily.height)
    if standard_error == 0:
        p_value = 0.0 if oriented_mean != 0 else 1.0
    else:
        p_value = erfc(abs(oriented_mean / standard_error) / sqrt(2))
    quintile_means = _quintile_means(scored)
    turnover = average_top_turnover(scored)
    yearly = year_segments(daily)
    regimes = regime_segments(daily, valid)
    industries = industry_segments(scored, config.minimum_pairs_per_date)
    missing_feature = frame.filter(
        pl.col("factor_value").is_null() | ~pl.col("factor_value").is_finite()
    ).height
    missing_label = frame.filter(
        pl.col("label_value").is_null() | ~pl.col("label_value").is_finite()
    ).height
    return FactorDiagnosticReport(
        trial_id=trial.trial_id,
        dataset_snapshot_id=trial.dataset_snapshot_id,
        feature_name=trial.feature_name,
        expected_direction=trial.expected_direction,
        total_sample_count=frame.height,
        valid_pair_count=valid.height,
        missing_feature_count=missing_feature,
        missing_label_count=missing_label,
        coverage=valid.height / frame.height,
        raw_mean_rank_ic=raw_mean,
        oriented_mean_rank_ic=oriented_mean,
        icir=icir,
        direction_consistency=daily.filter(pl.col("oriented_rank_ic") > 0).height / daily.height,
        p_value=p_value,
        quintile_mean_labels=quintile_means,
        quintile_monotonicity=_monotonicity(quintile_means),
        top_bottom_gross_return=quintile_means[4] - quintile_means[0],
        average_turnover=turnover,
        top_bottom_net_return=(
            quintile_means[4] - quintile_means[0] - turnover * config.round_trip_cost_bps / 10_000
        ),
        factor_autocorrelation=factor_autocorrelation(scored),
        size_exposure=size_exposure(scored),
        yearly_segments=yearly,
        regime_segments=regimes,
        industry_segments=industries,
        worst_year=min(yearly, key=lambda item: item.mean_rank_ic, default=None),
        worst_industry=min(industries, key=lambda item: item.mean_rank_ic, default=None),
    )


def _validate_input(frame: pl.DataFrame, config: DiagnosticConfig) -> None:
    required = {
        "decision_time",
        "symbol",
        "factor_value",
        "label_value",
        "log_total_mv",
        "industry",
        "market_regime",
    }
    missing = required.difference(frame.columns)
    if missing:
        detail = f"diagnostic frame is missing columns: {sorted(missing)}"
        raise FactorDiagnosticError(detail)
    if frame.is_empty() or config.minimum_pairs_per_date < _MINIMUM_CORRELATION_PAIRS:
        detail = "diagnostic frame and configuration must be non-empty"
        raise FactorDiagnosticError(detail)
    latest = frame["decision_time"].max()
    match latest:
        case datetime() as latest_time:
            if latest_time.date() > _DEVELOPMENT_END:
                detail = "diagnostic frame contains final holdout observations"
                raise FactorDiagnosticError(detail)
        case _:
            detail = "decision_time must contain timezone-aware datetimes"
            raise FactorDiagnosticError(detail)


def _ranked_frame(frame: pl.DataFrame, multiplier: float) -> pl.DataFrame:
    oriented = (pl.col("factor_value") * multiplier).alias("oriented_factor")
    return frame.with_columns(oriented).with_columns(
        pl.col("factor_value").rank("average").over("decision_time").alias("raw_rank"),
        pl.col("oriented_factor").rank("average").over("decision_time").alias("oriented_rank"),
        pl.col("label_value").rank("average").over("decision_time").alias("label_rank"),
    )


def _daily_rank_ic(frame: pl.DataFrame, minimum_pairs: int) -> pl.DataFrame:
    return (
        frame.group_by("decision_time")
        .agg(
            pl.len().alias("observations"),
            pl.corr("raw_rank", "label_rank").alias("raw_rank_ic"),
            pl.corr("oriented_rank", "label_rank").alias("oriented_rank_ic"),
        )
        .filter(
            (pl.col("observations") >= minimum_pairs)
            & pl.col("raw_rank_ic").is_finite()
            & pl.col("oriented_rank_ic").is_finite()
        )
        .sort("decision_time")
    )


def _quintile_means(frame: pl.DataFrame) -> tuple[float, float, float, float, float]:
    scored = frame.with_columns(
        (
            ((pl.col("oriented_rank") - 1) * 5 / pl.len().over("decision_time"))
            .floor()
            .add(1)
            .clip(1, 5)
            .cast(pl.Int8)
        ).alias("quintile")
    )
    values = tuple(
        _series_mean(scored.filter(pl.col("quintile") == quintile)["label_value"])
        for quintile in range(1, 6)
    )
    return values[0], values[1], values[2], values[3], values[4]


def _monotonicity(values: tuple[float, float, float, float, float]) -> float:
    return sum(current >= previous for previous, current in pairwise(values)) / 4


def _series_mean(series: pl.Series) -> float:
    value = series.mean()
    match value:
        case float() as result:
            return result
        case int() as result:
            return float(result)
        case _:
            detail = f"cannot calculate finite mean for {series.name}"
            raise FactorDiagnosticError(detail)


def _series_std(series: pl.Series) -> float:
    value = series.std(ddof=0)
    match value:
        case float() as result:
            return result
        case int() as result:
            return float(result)
        case _:
            return 0.0
