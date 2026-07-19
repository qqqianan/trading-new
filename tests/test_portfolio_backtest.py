import pytest

from ashare_lab.backtest.portfolio_engine import (
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    PortfolioBacktestInputError,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.portfolio import PortfolioResearchStatus, PortfolioRiskConfig

from .portfolio_backtest_support import bar, market, target, trading_date


def _risk_config() -> PortfolioRiskConfig:
    return PortfolioRiskConfig(
        max_position_weight=0.50,
        maximum_positions=30,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )


def test_portfolio_target_executes_for_multiple_symbols_at_next_open() -> None:
    # Given: a two-symbol target formed after the first session close.
    symbols = ("000001.SZ", "600000.SH")
    sessions = tuple(
        PortfolioSession(trading_date(day), tuple(bar(symbol, day, 10.0) for symbol in symbols))
        for day in range(3)
    )
    signal = PortfolioSignal(
        target(0, tuple((symbol, 0.40) for symbol in symbols)), market(symbols)
    )
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            minimum_commission=0.0,
            stamp_duty_rate=0.0,
            slippage_rate=0.0,
            portfolio_risk=_risk_config(),
        )
    )

    # When: the governed target is simulated.
    result = engine.run(sessions, (signal,))

    # Then: both board-lot buys fill on the following session and cash is conserved.
    assert {str(item.symbol): item.shares for item in result.positions} == {
        "000001.SZ": 4_000,
        "600000.SH": 4_000,
    }
    assert result.ending_cash == pytest.approx(20_000.0)
    assert {item.trading_date for item in result.trades} == {sessions[1].trading_date}


def test_missing_pit_industry_keeps_backtest_research_status_draft() -> None:
    # Given: a target without decision-time industry evidence.
    symbols = ("000001.SZ",)
    sessions = tuple(
        PortfolioSession(trading_date(day), (bar(symbols[0], day, 10.0),)) for day in range(2)
    )
    signal = PortfolioSignal(target(0, ((symbols[0], 0.30),)), market(symbols, industry=None))
    engine = PortfolioBacktestEngine(
        PortfolioBacktestConfig(initial_cash=100_000.0, portfolio_risk=_risk_config())
    )

    # When: the engine applies its mandatory portfolio risk stage.
    result = engine.run(sessions, (signal,))

    # Then: execution may be researched but the run cannot become validation eligible.
    assert result.research_status is PortfolioResearchStatus.DRAFT
    assert result.risk_decisions[0].status is PortfolioResearchStatus.DRAFT


def test_portfolio_backtest_rejects_negative_cost_assumption() -> None:
    # Given: a commission assumption that would create cash during a trade.
    config = PortfolioBacktestConfig(initial_cash=100_000.0, commission_rate=-0.001)

    # When / Then: the engine fails before any simulation can begin.
    with pytest.raises(PortfolioBacktestInputError, match="cost and slippage"):
        PortfolioBacktestEngine(config)


def test_portfolio_backtest_rejects_duplicate_session_dates() -> None:
    # Given: two cross-sections registered for the same trading date.
    session = PortfolioSession(trading_date(0), (bar("000001.SZ", 0, 10.0),))
    engine = PortfolioBacktestEngine(PortfolioBacktestConfig(initial_cash=100_000.0))

    # When / Then: ambiguous execution order is rejected before data use.
    with pytest.raises(PortfolioBacktestInputError, match="strictly increasing"):
        engine.run((session, session), ())
