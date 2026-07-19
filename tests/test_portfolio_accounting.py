import pytest

from ashare_lab.backtest.portfolio_engine import (
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.domain.trading import TradeSide
from ashare_lab.portfolio import PortfolioRiskConfig

from .portfolio_backtest_support import bar, market, target, trading_date


def test_portfolio_round_trip_cash_matches_hand_calculated_costs() -> None:
    # Given: a 5,000-share buy at CNY 10 and later sale at CNY 12.
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
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.001,
            minimum_commission=5.0,
            stamp_duty_rate=0.0005,
            slippage_rate=0.0,
            portfolio_risk=risk,
        )
    )

    # When: the round trip is executed.
    result = engine.run(sessions, signals)

    # Then: buy CNY 50 + sell CNY 60 commission and CNY 30 tax reconcile exactly.
    assert tuple(item.side for item in result.trades) == (TradeSide.BUY, TradeSide.SELL)
    assert result.total_fees == pytest.approx(140.0)
    assert result.ending_cash == pytest.approx(109_860.0)
    assert result.positions == ()


def test_five_symbol_buys_keep_fee_aware_cash_buffer() -> None:
    # Given: five equal 19% targets whose commissions consume additional cash.
    symbols = tuple(f"00000{index}.SZ" for index in range(1, 6))
    sessions = tuple(
        PortfolioSession(
            trading_date(day),
            tuple(bar(symbol, day, 10.0) for symbol in symbols),
        )
        for day in range(2)
    )
    signal = PortfolioSignal(
        target(0, tuple((symbol, 0.19) for symbol in symbols)), market(symbols)
    )
    risk = PortfolioRiskConfig(
        max_position_weight=0.20,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0003,
            minimum_commission=5.0,
            stamp_duty_rate=0.0005,
            slippage_rate=0.0,
            portfolio_risk=risk,
        )
    )

    # When: all buys are settled in stable symbol order.
    result = engine.run(sessions, (signal,))

    # Then: the final order loses one lot so fees cannot consume the 5% reserve.
    assert tuple(item.shares for item in result.positions) == (1_900, 1_900, 1_900, 1_900, 1_800)
    assert result.total_fees == pytest.approx(28.20)
    assert result.ending_cash == pytest.approx(5_971.80)
