"""Like-for-like annual and execution attribution for governed backtests."""

from collections import defaultdict
from typing import Literal

import numpy as np

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.research.model_attribution.models import (
    AnnualPerformanceAttribution,
    ExecutionConstraintAttribution,
)


class PortfolioAttributionError(Exception):
    """Compared backtests do not share one annual benchmark basis."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable comparison blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the attribution boundary and concrete blocker."""
        return f"portfolio_attribution: {self.detail}"


def annual_performance(
    baseline_report: PortfolioBacktestReport,
    model_report: PortfolioBacktestReport,
) -> tuple[AnnualPerformanceAttribution, ...]:
    """Compare annual net returns only when benchmark evidence agrees."""
    baseline = {item.year: item for item in baseline_report.metrics.annual_segments}
    model = {item.year: item for item in model_report.metrics.annual_segments}
    if not baseline or baseline.keys() != model.keys():
        detail = "baseline and model annual performance years differ"
        raise PortfolioAttributionError(detail)
    benchmarks_differ = any(
        not np.isclose(baseline[year].benchmark_return, model[year].benchmark_return)
        for year in baseline
    )
    if benchmarks_differ:
        detail = "baseline and model annual benchmarks differ"
        raise PortfolioAttributionError(detail)
    return tuple(
        AnnualPerformanceAttribution(
            year=year,
            baseline_return=baseline[year].portfolio_return,
            model_return=model[year].portfolio_return,
            return_gap=model[year].portfolio_return - baseline[year].portfolio_return,
            baseline_excess_return=baseline[year].excess_return,
            model_excess_return=model[year].excess_return,
            excess_return_gap=model[year].excess_return - baseline[year].excess_return,
        )
        for year in sorted(baseline)
    )


def risk_constraints(
    portfolio: Literal["BASELINE", "MODEL"],
    report: PortfolioBacktestReport,
) -> tuple[ExecutionConstraintAttribution, ...]:
    """Group immutable risk events without hiding repeated constraints."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    symbols: dict[tuple[str, str], set[str]] = defaultdict(set)
    for event in report.result.risk_events:
        key = (event.rule.value, event.action.value)
        counts[key] += 1
        if event.symbol is not None:
            symbols[key].add(str(event.symbol))
    return tuple(
        ExecutionConstraintAttribution(
            portfolio=portfolio,
            rule=rule,
            action=action,
            event_count=counts[(rule, action)],
            affected_symbols=len(symbols[(rule, action)]),
        )
        for rule, action in sorted(counts)
    )
