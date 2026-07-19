"""Input structure and mandatory per-symbol data quality validation."""

from typing import TYPE_CHECKING

from ashare_lab.backtest.portfolio_contracts import (
    PortfolioBacktestInputError,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.domain.quality import DataQualityReport
from ashare_lab.research.data_quality import DataQualityGuard

if TYPE_CHECKING:
    from ashare_lab.domain.market import MarketBar, Symbol


def validate_portfolio_inputs(
    sessions: tuple[PortfolioSession, ...],
    signals: tuple[PortfolioSignal, ...],
) -> tuple[DataQualityReport, ...]:
    """Reject ambiguous sessions then run every symbol through the hard data gate."""
    if not sessions:
        detail = "at least one session is required"
        raise PortfolioBacktestInputError(detail)
    dates = tuple(item.trading_date for item in sessions)
    if dates != tuple(sorted(set(dates))):
        detail = "session dates must be strictly increasing and unique"
        raise PortfolioBacktestInputError(detail)
    signal_dates = tuple(item.target.decision_date for item in signals)
    if len(signal_dates) != len(set(signal_dates)) or set(signal_dates) - set(dates):
        detail = "signals must be unique and belong to a session close"
        raise PortfolioBacktestInputError(detail)
    by_symbol: dict[Symbol, list[MarketBar]] = {}
    for session in sessions:
        symbols = tuple(bar.symbol for bar in session.bars)
        if not symbols or len(symbols) != len(set(symbols)):
            detail = "every session requires unique bars"
            raise PortfolioBacktestInputError(detail)
        if any(bar.trading_date != session.trading_date for bar in session.bars):
            detail = "bar dates must match their portfolio session"
            raise PortfolioBacktestInputError(detail)
        for bar in session.bars:
            by_symbol.setdefault(bar.symbol, []).append(bar)
    return tuple(DataQualityGuard().validate(tuple(bars)) for bars in by_symbol.values())
