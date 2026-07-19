from ashare_lab.backtest.portfolio_engine import (
    OrderBlockReason,
    OrderStatus,
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.domain.risk import RiskLimits, RiskRule
from ashare_lab.portfolio import PortfolioRiskConfig

from .portfolio_backtest_support import BarOptions, bar, market, target, trading_date


def test_risk_exit_retries_across_limit_down_and_suspension() -> None:
    # Given: a concentrated holding falls through the drawdown circuit breaker.
    symbol = "000001.SZ"
    sessions = (
        PortfolioSession(trading_date(0), (bar(symbol, 0, 10.0),)),
        PortfolioSession(trading_date(1), (bar(symbol, 1, 10.0),)),
        PortfolioSession(trading_date(2), (bar(symbol, 2, 8.0),)),
        PortfolioSession(trading_date(3), (bar(symbol, 3, 8.0, BarOptions(limit_down=True)),)),
        PortfolioSession(trading_date(4), (bar(symbol, 4, 8.0, BarOptions(suspended=True)),)),
        PortfolioSession(trading_date(5), (bar(symbol, 5, 8.0),)),
    )
    signal = PortfolioSignal(target(0, ((symbol, 0.95),)), market((symbol,)))
    risk = PortfolioRiskConfig(
        max_position_weight=0.95,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    circuit = RiskLimits(
        max_position_weight=0.95,
        minimum_cash_weight=0.05,
        max_volume_participation=1.0,
        max_drawdown=0.10,
        max_daily_loss=0.50,
        max_position_loss=0.50,
    )
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            minimum_commission=0.0,
            stamp_duty_rate=0.0,
            slippage_rate=0.0,
            portfolio_risk=risk,
            circuit_limits=circuit,
        )
    )

    # When: the position is held through blocked exit sessions.
    result = engine.run(sessions, (signal,))

    # Then: exit intent remains pending until the first tradable open.
    assert result.positions == ()
    blocked = tuple(item for item in result.orders if item.status is OrderStatus.PENDING)
    assert tuple(item.reason for item in blocked) == (
        OrderBlockReason.LIMIT_DOWN,
        OrderBlockReason.SUSPENDED,
    )
    assert RiskRule.MAX_DRAWDOWN in {item.rule for item in result.risk_events}
    assert sum(item.rule is RiskRule.EXIT_BLOCKED for item in result.risk_events) == 2


def test_partially_filled_risk_exit_audits_retained_remainder() -> None:
    # Given: a drawdown exit whose next session volume can sell only 5,000 shares.
    symbol = "000001.SZ"
    sessions = (
        PortfolioSession(trading_date(0), (bar(symbol, 0, 10.0),)),
        PortfolioSession(trading_date(1), (bar(symbol, 1, 10.0),)),
        PortfolioSession(trading_date(2), (bar(symbol, 2, 8.0),)),
        PortfolioSession(trading_date(3), (bar(symbol, 3, 8.0, BarOptions(volume=100_000)),)),
        PortfolioSession(trading_date(4), (bar(symbol, 4, 8.0, BarOptions(volume=100_000)),)),
    )
    signal = PortfolioSignal(target(0, ((symbol, 0.95),)), market((symbol,)))
    portfolio_risk = PortfolioRiskConfig(
        max_position_weight=0.95,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=0.05,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    circuit = RiskLimits(
        max_position_weight=0.95,
        minimum_cash_weight=0.05,
        max_volume_participation=1.0,
        max_drawdown=0.10,
        max_daily_loss=0.50,
        max_position_loss=0.50,
    )
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            minimum_commission=0.0,
            stamp_duty_rate=0.0,
            slippage_rate=0.0,
            portfolio_risk=portfolio_risk,
            circuit_limits=circuit,
        )
    )

    # When: the capacity-constrained risk exit is retried.
    result = engine.run(sessions, (signal,))

    # Then: the partial fill and retained remainder are both explicit.
    risk_orders = tuple(item for item in result.orders if item.risk_exit)
    assert risk_orders[0].status is OrderStatus.PARTIAL
    assert risk_orders[0].reason is OrderBlockReason.VOLUME_CAPACITY
    assert RiskRule.EXIT_BLOCKED in {item.rule for item in result.risk_events}
    assert result.positions == ()
