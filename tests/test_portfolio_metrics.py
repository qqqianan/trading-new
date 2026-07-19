import pytest

from ashare_lab.backtest.portfolio_engine import (
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.backtest.portfolio_metrics import BenchmarkPoint, calculate_portfolio_metrics
from ashare_lab.portfolio import PortfolioRiskConfig

from .portfolio_backtest_support import bar, market, target, trading_date


def test_portfolio_metrics_report_benchmark_cost_turnover_and_capacity() -> None:
    # Given: a deterministic profitable round trip and aligned benchmark path.
    symbol = "000001.SZ"
    sessions = (
        PortfolioSession(trading_date(0), (bar(symbol, 0, 10.0),)),
        PortfolioSession(trading_date(1), (bar(symbol, 1, 10.0),)),
        PortfolioSession(trading_date(2), (bar(symbol, 2, 12.0),)),
        PortfolioSession(trading_date(3), (bar(symbol, 3, 12.0),)),
    )
    signals = (
        PortfolioSignal(target(0, ((symbol, 0.50),)), market((symbol,))),
        PortfolioSignal(target(1, ((symbol, 0.0),)), market((symbol,))),
    )
    risk = PortfolioRiskConfig(
        max_position_weight=0.50,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    result = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.001,
            minimum_commission=5.0,
            stamp_duty_rate=0.0005,
            slippage_rate=0.0,
            portfolio_risk=risk,
        )
    ).run(sessions, signals)
    benchmark = tuple(
        BenchmarkPoint(trading_date(index), value)
        for index, value in enumerate((100.0, 100.0, 110.0, 110.0))
    )

    # When: net portfolio performance is compared with the benchmark.
    metrics = calculate_portfolio_metrics(result, benchmark)

    # Then: absolute, excess, cost, turnover, capacity, and annual segments are disclosed.
    assert metrics.total_return == pytest.approx(0.0986)
    assert metrics.benchmark_return == pytest.approx(0.10)
    assert metrics.excess_return == pytest.approx(-0.0014)
    assert metrics.total_fees == pytest.approx(140.0)
    assert metrics.turnover > 1.0
    assert metrics.maximum_volume_participation == pytest.approx(0.005)
    assert len(metrics.annual_segments) == 2
