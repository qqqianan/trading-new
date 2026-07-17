"""Deterministic Asia/Shanghai nightly data-maintenance plan."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique


@unique
class NightlyStage(StrEnum):
    """Closed governed maintenance stages."""

    MARKET = "market"
    BENCHMARK_DAILY = "benchmark_daily"
    DIVIDENDS = "dividends"
    INCOME = "income"
    BALANCE_SHEET = "balance_sheet"
    CASHFLOW = "cashflow"
    FINANCIAL_INDICATORS = "financial_indicators"
    UNIVERSE = "universe"
    REFERENCE_DATA = "reference_data"


@dataclass(frozen=True, slots=True)
class NightlyPlan:
    """One run date and its ordered idempotent stages."""

    run_date: date
    stages: tuple[NightlyStage, ...]


def build_nightly_plan(run_date: date) -> NightlyPlan:
    """Build daily core work plus one bounded weekday maintenance stage."""
    stages = (
        NightlyStage.MARKET,
        NightlyStage.BENCHMARK_DAILY,
        NightlyStage.DIVIDENDS,
    )
    weekly: tuple[NightlyStage | None, ...] = (
        NightlyStage.INCOME,
        NightlyStage.BALANCE_SHEET,
        NightlyStage.CASHFLOW,
        NightlyStage.FINANCIAL_INDICATORS,
        NightlyStage.UNIVERSE,
        NightlyStage.REFERENCE_DATA,
        None,
    )
    stage = weekly[run_date.weekday()]
    return NightlyPlan(run_date, stages if stage is None else (*stages, stage))
