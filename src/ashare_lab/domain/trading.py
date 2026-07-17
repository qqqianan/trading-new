"""Backtest result value objects."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique

from ashare_lab.domain.market import Symbol
from ashare_lab.domain.quality import DataQualityReport
from ashare_lab.domain.risk import RiskEvent


@unique
class TradeSide(StrEnum):
    """Supported long-only trade directions."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Trade:
    """A completed simulated fill."""

    trading_date: date
    symbol: Symbol
    side: TradeSide
    quantity: int
    price: float
    notional: float
    commission: float
    stamp_duty: float
    realized_pnl: float | None


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """End-of-day account equity."""

    trading_date: date
    equity: float
    cash: float
    market_value: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Raw engine output before performance metrics are derived."""

    symbol: Symbol
    initial_cash: float
    ending_cash: float
    ending_shares: int
    total_fees: float
    data_quality: DataQualityReport
    risk_events: tuple[RiskEvent, ...]
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]
