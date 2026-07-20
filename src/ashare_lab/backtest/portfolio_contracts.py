"""Typed contracts for multi-asset A-share backtesting."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique

from ashare_lab.domain.market import MarketBar, Symbol
from ashare_lab.domain.quality import DataQualityReport
from ashare_lab.domain.risk import RiskEvent, RiskLimits
from ashare_lab.domain.trading import Trade, TradeSide
from ashare_lab.portfolio import (
    PortfolioMarketSnapshot,
    PortfolioResearchStatus,
    PortfolioRiskConfig,
    PortfolioRiskDecision,
    PortfolioTarget,
)


@dataclass(frozen=True, slots=True)
class PortfolioBacktestInputError(Exception):
    """Portfolio sessions or assumptions violate the simulation boundary."""

    detail: str

    def __str__(self) -> str:
        """Return the backtest boundary and concrete failure."""
        return f"portfolio_backtest_input: {self.detail}"


@unique
class OrderStatus(StrEnum):
    """Observable outcome of one daily execution attempt."""

    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    PENDING = "PENDING"


@unique
class OrderBlockReason(StrEnum):
    """Stable execution reasons retained in the order audit trail."""

    FILLED = "FILLED"
    SUSPENDED = "SUSPENDED"
    LIMIT_UP = "LIMIT_UP"
    LIMIT_DOWN = "LIMIT_DOWN"
    T_PLUS_ONE = "T_PLUS_ONE"
    VOLUME_CAPACITY = "VOLUME_CAPACITY"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    MISSING_BAR = "MISSING_BAR"


@dataclass(frozen=True, slots=True)
class PortfolioSession:
    """One trading date and its raw execution bars."""

    trading_date: date
    bars: tuple[MarketBar, ...]
    suspended_symbols: tuple[Symbol, ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioSignal:
    """Close-generated target plus decision-time market risk evidence."""

    target: PortfolioTarget
    market: tuple[PortfolioMarketSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    """Ending marked position with auditable cost and T+1 date."""

    symbol: Symbol
    shares: int
    total_cost: float
    acquired_on: date
    last_price: float


@dataclass(frozen=True, slots=True)
class PortfolioOrderRecord:
    """One filled, partial, or retained daily order attempt."""

    trading_date: date
    symbol: Symbol
    side: TradeSide
    requested_quantity: int
    filled_quantity: int
    status: OrderStatus
    reason: OrderBlockReason
    risk_exit: bool
    volume_participation: float


@dataclass(frozen=True, slots=True)
class PortfolioEquityPoint:
    """End-of-day multi-asset account mark."""

    trading_date: date
    equity: float
    cash: float
    market_value: float


@dataclass(frozen=True, slots=True)
class PortfolioExecutionAssumptions:
    """Frozen costs and execution limits disclosed with every result."""

    commission_rate: float
    minimum_commission: float
    stamp_duty_rate: float
    slippage_rate: float
    board_lot: int


@dataclass(frozen=True, slots=True)
class PortfolioBacktestResult:
    """Complete multi-asset ledger before performance reporting."""

    initial_cash: float
    ending_cash: float
    execution_assumptions: PortfolioExecutionAssumptions
    portfolio_risk_config: PortfolioRiskConfig
    circuit_limits: RiskLimits
    positions: tuple[PortfolioPosition, ...]
    total_fees: float
    data_quality: tuple[DataQualityReport, ...]
    risk_events: tuple[RiskEvent, ...]
    risk_decisions: tuple[PortfolioRiskDecision, ...]
    orders: tuple[PortfolioOrderRecord, ...]
    trades: tuple[Trade, ...]
    equity_curve: tuple[PortfolioEquityPoint, ...]
    research_status: PortfolioResearchStatus


@dataclass(frozen=True, slots=True)
class ExecutionBatch:
    """Account mutations and audit records from one session open."""

    trades: tuple[Trade, ...]
    orders: tuple[PortfolioOrderRecord, ...]
    risk_events: tuple[RiskEvent, ...]
    has_pending: bool
