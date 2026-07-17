"""Internal application result models."""

from dataclasses import dataclass, field
from datetime import date

from ashare_lab.backtest.metrics import PerformanceMetrics
from ashare_lab.domain.market import Instrument, Symbol
from ashare_lab.domain.risk import RiskLimits
from ashare_lab.domain.trading import BacktestResult


@dataclass(frozen=True, slots=True)
class BacktestParameters:
    """Validated parameters passed from the API boundary."""

    symbol: Symbol
    initial_cash: float
    short_window: int
    long_window: int
    allocation: float
    risk_limits: RiskLimits = field(default_factory=RiskLimits)


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Engine result enriched with metrics and instrument metadata."""

    instrument: Instrument
    source_name: str
    result: BacktestResult
    metrics: PerformanceMetrics
    risk_limits: RiskLimits


@dataclass(frozen=True, slots=True)
class WatchItem:
    """Latest quote-like snapshot for one instrument."""

    symbol: Symbol
    name: str
    close: float
    change_percent: float
    volume: int


@dataclass(frozen=True, slots=True)
class MarketPoint:
    """Equal-weighted normalized demo market point."""

    trading_date: date
    value: float


@dataclass(frozen=True, slots=True)
class MarketOverview:
    """Overview data used by the research dashboard."""

    source_name: str
    as_of_date: date
    watchlist: tuple[WatchItem, ...]
    market_curve: tuple[MarketPoint, ...]
    advancing: int
    declining: int
    unchanged: int
