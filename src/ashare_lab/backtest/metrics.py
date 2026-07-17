"""Portfolio-level return and risk metrics."""

from dataclasses import dataclass
from math import sqrt
from typing import Final

import numpy as np

from ashare_lab.domain.trading import BacktestResult, TradeSide

TRADING_DAYS_PER_YEAR: Final = 252


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """Compact metrics suitable for API serialization."""

    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    total_fees: float


def calculate_metrics(result: BacktestResult) -> PerformanceMetrics:
    """Calculate metrics from net-of-fee daily account equity."""
    equities = np.asarray([point.equity for point in result.equity_curve], dtype=np.float64)
    total_return = float(equities[-1] / equities[0] - 1.0)
    periods = max(len(equities) - 1, 1)
    annualized_return = float(
        (equities[-1] / equities[0]) ** (TRADING_DAYS_PER_YEAR / periods) - 1.0
    )

    returns = np.diff(equities) / equities[:-1]
    return_std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    volatility = return_std * sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (
        float(np.mean(returns)) / return_std * sqrt(TRADING_DAYS_PER_YEAR)
        if return_std > 0.0
        else 0.0
    )
    peaks = np.maximum.accumulate(equities)
    max_drawdown = float(np.min(equities / peaks - 1.0))
    sells = [trade for trade in result.trades if trade.side is TradeSide.SELL]
    wins = sum(1 for trade in sells if trade.realized_pnl is not None and trade.realized_pnl > 0.0)
    win_rate = wins / len(sells) if sells else 0.0
    return PerformanceMetrics(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=volatility,
        sharpe_ratio=sharpe,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        trade_count=len(result.trades),
        total_fees=result.total_fees,
    )
