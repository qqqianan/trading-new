from datetime import UTC, date, datetime, time, timedelta

from ashare_lab.backtest.engine import BacktestEngine, EngineConfig
from ashare_lab.backtest.risk import RiskLimits, RiskRule
from ashare_lab.domain.market import MarketBar, PriceBasis, Symbol


def _bar(
    day: int,
    price: float,
    *,
    suspended: bool = False,
    at_limit_up: bool = False,
) -> MarketBar:
    trading_date = date(2025, 1, 2) + timedelta(days=day)
    limit_up = price if at_limit_up else price * 1.1
    return MarketBar(
        symbol=Symbol("600000.SH"),
        trading_date=trading_date,
        available_at=datetime.combine(trading_date, time(15, 5), tzinfo=UTC),
        price_basis=PriceBasis.RAW,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1_000_000,
        previous_close=price,
        limit_up=limit_up,
        limit_down=price * 0.9,
        is_suspended=suspended,
    )


def test_signal_at_close_executes_at_next_open_in_board_lots() -> None:
    # Given: a long signal produced on day zero.
    bars = tuple(_bar(day, 10.0) for day in range(3))
    targets = (1.0, 1.0, 1.0)
    engine = BacktestEngine(EngineConfig(initial_cash=100_000.0, allocation=0.95))

    # When: the path is backtested.
    result = engine.run(bars, targets)

    # Then: the first fill is next day and its quantity is a 100-share lot.
    assert len(result.trades) == 1
    assert result.trades[0].trading_date == bars[1].trading_date
    assert result.trades[0].quantity % 100 == 0


def test_buy_order_waits_through_suspension_and_limit_up() -> None:
    # Given: a buy signal followed by a suspension and a limit-up open.
    bars = (
        _bar(0, 10.0),
        _bar(1, 10.0, suspended=True),
        _bar(2, 10.0, at_limit_up=True),
        _bar(3, 10.0),
    )
    targets = (1.0, 1.0, 1.0, 1.0)
    engine = BacktestEngine(EngineConfig(initial_cash=100_000.0, allocation=0.95))

    # When: the order is processed across the blocked sessions.
    result = engine.run(bars, targets)

    # Then: it fills on the first tradable open.
    assert len(result.trades) == 1
    assert result.trades[0].trading_date == bars[3].trading_date


def test_drawdown_circuit_breaker_liquidates_at_next_open() -> None:
    # Given: a position whose close falls through the 10% portfolio drawdown limit.
    bars = (_bar(0, 10.0), _bar(1, 10.0), _bar(2, 8.0), _bar(3, 8.0))
    targets = (1.0, 1.0, 1.0, 1.0)
    limits = RiskLimits(
        max_position_weight=0.95,
        minimum_cash_weight=0.05,
        max_volume_participation=1.0,
        max_drawdown=0.1,
        max_daily_loss=0.5,
        max_position_loss=0.5,
    )
    engine = BacktestEngine(
        EngineConfig(initial_cash=100_000.0, allocation=0.95, risk_limits=limits)
    )

    # When: the path is simulated without a strategy exit signal.
    result = engine.run(bars, targets)

    # Then: risk forces a sell on the following open and halts new exposure.
    assert len(result.trades) == 2
    assert result.trades[-1].trading_date == bars[3].trading_date
    assert result.ending_shares == 0
    assert result.risk_events[-1].rule is RiskRule.MAX_DRAWDOWN
