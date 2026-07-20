from ashare_lab.backtest.costs import ChinaACommission
from ashare_lab.backtest.portfolio_account import PortfolioAccount
from ashare_lab.backtest.portfolio_engine import (
    OrderBlockReason,
    OrderStatus,
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.backtest.portfolio_execution import ExecutionPolicy, ExecutionRequest
from ashare_lab.domain.market import Symbol
from ashare_lab.portfolio import PortfolioRiskConfig

from .portfolio_backtest_support import BarOptions, bar, market, target, trading_date


def test_volume_constrained_buy_stays_pending_and_retries() -> None:
    # Given: the first execution session cannot support one board lot.
    symbol = "000001.SZ"
    sessions = (
        PortfolioSession(trading_date(0), (bar(symbol, 0, 10.0),)),
        PortfolioSession(trading_date(1), (bar(symbol, 1, 10.0, BarOptions(volume=1_000)),)),
        PortfolioSession(trading_date(2), (bar(symbol, 2, 10.0, BarOptions(volume=1_000_000)),)),
    )
    signal = PortfolioSignal(target(0, ((symbol, 0.30),)), market((symbol,)))
    risk = PortfolioRiskConfig(
        max_position_weight=0.50,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=0.05,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            minimum_commission=0.0,
            stamp_duty_rate=0.0,
            slippage_rate=0.0,
            portfolio_risk=risk,
        )
    )

    # When: the engine retries the target on later sessions.
    result = engine.run(sessions, (signal,))

    # Then: the first attempt is pending and the later liquid session fills it.
    assert result.positions[0].shares == 3_000
    assert any(
        item.status is OrderStatus.PENDING and item.reason is OrderBlockReason.VOLUME_CAPACITY
        for item in result.orders
    )


def test_same_day_acquisition_lot_is_not_sellable() -> None:
    # Given: an account that acquired 3,000 shares at this session open.
    symbol = Symbol("000001.SZ")
    session = PortfolioSession(trading_date(0), (bar(str(symbol), 0, 10.0),))
    policy = ExecutionPolicy(1.0, 0.0, 0.05, ChinaACommission(0.0, 0.0, 0.0))
    account = PortfolioAccount(100_000.0)
    account.execute(
        ExecutionRequest(session=session, weights={symbol: 0.30}, policy=policy, risk_exit=False)
    )

    # When: a sell target is attempted on the acquisition date.
    batch = account.execute(
        ExecutionRequest(session=session, weights={symbol: 0.0}, policy=policy, risk_exit=False)
    )

    # Then: the exact tax lot remains pending under T+1.
    assert batch.trades == ()
    assert batch.orders[0].reason is OrderBlockReason.T_PLUS_ONE
    assert account.snapshots()[0].shares == 3_000


def test_limit_up_buy_is_retained_until_a_tradable_open() -> None:
    # Given: the first execution open is at the upper price limit.
    symbol = "000001.SZ"
    sessions = (
        PortfolioSession(trading_date(0), (bar(symbol, 0, 10.0),)),
        PortfolioSession(trading_date(1), (bar(symbol, 1, 10.0, BarOptions(limit_up=True)),)),
        PortfolioSession(trading_date(2), (bar(symbol, 2, 10.0),)),
    )
    signal = PortfolioSignal(target(0, ((symbol, 0.30),)), market((symbol,)))
    risk = PortfolioRiskConfig(
        max_position_weight=0.50,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            minimum_commission=0.0,
            stamp_duty_rate=0.0,
            slippage_rate=0.0,
            portfolio_risk=risk,
        )
    )

    # When: the retained target reaches the next open.
    result = engine.run(sessions, (signal,))

    # Then: the blocked attempt is audited before the later fill.
    assert result.positions[0].shares == 3_000
    assert result.orders[0].reason is OrderBlockReason.LIMIT_UP
    assert result.orders[-1].status is OrderStatus.FILLED


def test_sparse_suspension_event_blocks_missing_daily_bar_as_suspended() -> None:
    # Given: a retained buy whose next session has a suspension event but no daily bar.
    symbol = "000001.SZ"
    other = "000002.SZ"
    sessions = (
        PortfolioSession(trading_date(0), (bar(symbol, 0, 10.0),)),
        PortfolioSession(
            trading_date(1),
            (bar(other, 1, 10.0),),
            suspended_symbols=(Symbol(symbol),),
        ),
    )
    signal = PortfolioSignal(target(0, ((symbol, 0.30),)), market((symbol,)))
    risk = PortfolioRiskConfig(
        max_position_weight=0.50,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(initial_cash=100_000.0, portfolio_risk=risk)
    )

    # When: execution reconciles the sparse suspension session.
    result = engine.run(sessions, (signal,))

    # Then: the pending attempt keeps the specific exchange-state reason.
    assert result.orders[0].reason is OrderBlockReason.SUSPENDED
