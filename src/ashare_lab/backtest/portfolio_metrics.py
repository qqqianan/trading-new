"""Net portfolio, benchmark, capacity, and annual performance metrics."""

from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Final

import numpy as np

from ashare_lab.backtest.portfolio_contracts import OrderStatus, PortfolioBacktestResult

TRADING_DAYS_PER_YEAR: Final = 252


@dataclass(frozen=True, slots=True)
class BenchmarkPoint:
    """One aligned benchmark close level."""

    trading_date: date
    value: float


@dataclass(frozen=True, slots=True)
class AnnualPortfolioMetric:
    """Net absolute and benchmark return for one calendar year."""

    year: int
    portfolio_return: float
    benchmark_return: float
    excess_return: float


@dataclass(frozen=True, slots=True)
class PortfolioPerformanceMetrics:
    """Cost-aware multi-asset performance and execution disclosure."""

    total_return: float
    benchmark_return: float
    excess_return: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    turnover: float
    total_fees: float
    maximum_volume_participation: float
    pending_order_count: int
    risk_event_count: int
    annual_segments: tuple[AnnualPortfolioMetric, ...]


@dataclass(frozen=True, slots=True)
class PortfolioMetricInputError(Exception):
    """Benchmark evidence is not aligned with the portfolio curve."""

    detail: str

    def __str__(self) -> str:
        """Return the metric boundary and concrete alignment failure."""
        return f"portfolio_metric_input: {self.detail}"


def calculate_portfolio_metrics(
    result: PortfolioBacktestResult,
    benchmark: tuple[BenchmarkPoint, ...],
) -> PortfolioPerformanceMetrics:
    """Calculate net metrics without hiding pending orders or risk events."""
    dates = tuple(item.trading_date for item in result.equity_curve)
    benchmark_dates = tuple(item.trading_date for item in benchmark)
    if not dates or dates != benchmark_dates:
        detail = "benchmark dates must exactly match the non-empty equity curve"
        raise PortfolioMetricInputError(detail)
    benchmark_values = np.asarray([item.value for item in benchmark], dtype=np.float64)
    if not np.all(np.isfinite(benchmark_values)) or np.any(benchmark_values <= 0):
        detail = "benchmark values must be finite and positive"
        raise PortfolioMetricInputError(detail)
    equities = np.asarray([item.equity for item in result.equity_curve], dtype=np.float64)
    returns = np.diff(equities) / equities[:-1]
    return_std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    volatility = return_std * sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (
        float(np.mean(returns)) / return_std * sqrt(TRADING_DAYS_PER_YEAR)
        if return_std > 0
        else 0.0
    )
    peaks = np.maximum.accumulate(equities)
    total_return = float(equities[-1] / result.initial_cash - 1.0)
    benchmark_return = float(benchmark_values[-1] / benchmark_values[0] - 1.0)
    average_equity = float(np.mean(equities))
    turnover = sum(item.notional for item in result.trades) / average_equity
    return PortfolioPerformanceMetrics(
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
        annualized_volatility=volatility,
        sharpe_ratio=sharpe,
        max_drawdown=float(np.min(equities / peaks - 1.0)),
        turnover=turnover,
        total_fees=result.total_fees,
        maximum_volume_participation=max(
            (item.volume_participation for item in result.orders), default=0.0
        ),
        pending_order_count=sum(item.status is not OrderStatus.FILLED for item in result.orders),
        risk_event_count=len(result.risk_events),
        annual_segments=_annual_segments(dates, equities, benchmark_values),
    )


def _annual_segments(
    dates: tuple[date, ...],
    equities: np.ndarray[tuple[int], np.dtype[np.float64]],
    benchmark: np.ndarray[tuple[int], np.dtype[np.float64]],
) -> tuple[AnnualPortfolioMetric, ...]:
    values: list[AnnualPortfolioMetric] = []
    for year in sorted({item.year for item in dates}):
        indexes = tuple(index for index, item in enumerate(dates) if item.year == year)
        first = indexes[0]
        last = indexes[-1]
        portfolio_return = float(equities[last] / equities[first] - 1.0)
        benchmark_return = float(benchmark[last] / benchmark[first] - 1.0)
        values.append(
            AnnualPortfolioMetric(
                year,
                portfolio_return,
                benchmark_return,
                portfolio_return - benchmark_return,
            )
        )
    return tuple(values)
