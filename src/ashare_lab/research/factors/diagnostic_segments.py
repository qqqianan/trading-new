"""Turnover, persistence, exposure, and disclosed segment diagnostics."""

from datetime import datetime
from itertools import pairwise

import polars as pl
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ashare_lab.research.factors.models import SegmentMetric

_SEGMENTS = TypeAdapter(tuple[SegmentMetric, ...])
_TOP_QUINTILE = 5
_MINIMUM_TURNOVER_DATES = 2


class _TopMembership(BaseModel):
    """Parsed same-date top portfolio membership used for turnover."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_time: datetime
    members: tuple[str, ...]


_TOP_MEMBERSHIPS = TypeAdapter(tuple[_TopMembership, ...])


def average_top_turnover(frame: pl.DataFrame) -> float:
    """Return average one-way membership turnover for the oriented top quintile."""
    top = frame.with_columns(
        (
            ((pl.col("oriented_rank") - 1) * 5 / pl.len().over("decision_time"))
            .floor()
            .add(1)
            .clip(1, 5)
            .cast(pl.Int8)
        ).alias("quintile")
    ).filter(pl.col("quintile") == _TOP_QUINTILE)
    sets = (
        top.group_by("decision_time")
        .agg(pl.col("symbol").unique().sort().alias("members"))
        .sort("decision_time")
    )
    memberships = _TOP_MEMBERSHIPS.validate_json(sets.write_json())
    if len(memberships) < _MINIMUM_TURNOVER_DATES:
        return 0.0
    turnovers = tuple(
        1 - len(set(current.members).intersection(previous.members)) / len(current.members)
        for previous, current in pairwise(memberships)
    )
    return sum(turnovers) / len(turnovers)


def factor_autocorrelation(frame: pl.DataFrame) -> float:
    """Return mean cross-sectional rank persistence between adjacent decisions."""
    date_map = (
        frame.select("decision_time")
        .unique()
        .sort("decision_time")
        .with_columns(pl.col("decision_time").shift(1).alias("previous_time"))
        .drop_nulls("previous_time")
    )
    prior = frame.select(
        "symbol",
        pl.col("decision_time").alias("previous_time"),
        pl.col("oriented_rank").alias("previous_rank"),
    )
    pairs = frame.join(date_map, on="decision_time").join(
        prior,
        on=["symbol", "previous_time"],
    )
    daily = (
        pairs.group_by("decision_time")
        .agg(pl.corr("oriented_rank", "previous_rank").alias("correlation"))
        .filter(pl.col("correlation").is_finite())
    )
    return _mean_or_zero(daily["correlation"])


def size_exposure(frame: pl.DataFrame) -> float:
    """Return mean same-date correlation with point-in-time log market value."""
    daily = (
        frame.filter(pl.col("log_total_mv").is_not_null() & pl.col("log_total_mv").is_finite())
        .group_by("decision_time")
        .agg(pl.corr("oriented_factor", "log_total_mv").alias("correlation"))
        .filter(pl.col("correlation").is_finite())
    )
    return max(-1.0, min(1.0, _mean_or_zero(daily["correlation"])))


def year_segments(daily: pl.DataFrame) -> tuple[SegmentMetric, ...]:
    """Disclose every development calendar year, including the worst one."""
    grouped = (
        daily.with_columns(pl.col("decision_time").dt.year().cast(pl.String).alias("segment"))
        .group_by("segment")
        .agg(
            pl.col("observations").sum().alias("observations"),
            pl.col("oriented_rank_ic").mean().alias("mean_rank_ic"),
        )
        .sort("segment")
    )
    return _parse_segments(grouped)


def regime_segments(daily: pl.DataFrame, frame: pl.DataFrame) -> tuple[SegmentMetric, ...]:
    """Disclose all precomputed market regimes without selecting the best state."""
    regimes = frame.select("decision_time", "market_regime").unique()
    grouped = (
        daily.join(regimes, on="decision_time")
        .group_by("market_regime")
        .agg(
            pl.col("observations").sum().alias("observations"),
            pl.col("oriented_rank_ic").mean().alias("mean_rank_ic"),
        )
        .rename({"market_regime": "segment"})
        .sort("segment")
    )
    return _parse_segments(grouped)


def industry_segments(
    frame: pl.DataFrame,
    minimum_pairs: int,
) -> tuple[SegmentMetric, ...]:
    """Disclose within-industry IC where PIT industry evidence is available."""
    daily = (
        frame.filter(pl.col("industry").is_not_null())
        .group_by("decision_time", "industry")
        .agg(
            pl.len().alias("observations"),
            pl.corr("oriented_rank", "label_rank").alias("rank_ic"),
        )
        .filter((pl.col("observations") >= minimum_pairs) & pl.col("rank_ic").is_finite())
    )
    grouped = (
        daily.group_by("industry")
        .agg(
            pl.col("observations").sum().alias("observations"),
            pl.col("rank_ic").mean().alias("mean_rank_ic"),
        )
        .rename({"industry": "segment"})
        .sort("segment")
    )
    return _parse_segments(grouped)


def _parse_segments(frame: pl.DataFrame) -> tuple[SegmentMetric, ...]:
    return _SEGMENTS.validate_json(frame.write_json())


def _mean_or_zero(series: pl.Series) -> float:
    value = series.mean()
    match value:
        case float() as result:
            return result
        case int() as result:
            return float(result)
        case _:
            return 0.0
