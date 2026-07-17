"""Immutable risk policy and audit event value objects."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique


@unique
class RiskRule(StrEnum):
    """Stable codes for auditable risk decisions."""

    MAX_POSITION_WEIGHT = "max_position_weight"
    MINIMUM_CASH_WEIGHT = "minimum_cash_weight"
    VOLUME_PARTICIPATION = "volume_participation"
    MAX_DRAWDOWN = "max_drawdown"
    MAX_DAILY_LOSS = "max_daily_loss"
    MAX_POSITION_LOSS = "max_position_loss"
    EXIT_BLOCKED = "exit_blocked"


@unique
class RiskAction(StrEnum):
    """Actions the execution engine must honor."""

    RESIZE = "resize"
    REJECT = "reject"
    HALT_AND_LIQUIDATE = "halt_and_liquidate"
    RETRY_EXIT = "retry_exit"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Portfolio and execution limits for a daily long-only strategy."""

    max_position_weight: float = 0.95
    minimum_cash_weight: float = 0.05
    max_volume_participation: float = 0.10
    max_drawdown: float = 0.20
    max_daily_loss: float = 0.08
    max_position_loss: float = 0.15


@dataclass(frozen=True, slots=True)
class RiskEvent:
    """One explainable risk decision or circuit-breaker trigger."""

    trading_date: date
    rule: RiskRule
    action: RiskAction
    observed: float
    limit: float
    message: str


@dataclass(frozen=True, slots=True)
class RiskSizingDecision:
    """Risk-adjusted board-lot quantity with any binding events."""

    quantity: int
    events: tuple[RiskEvent, ...]


@dataclass(frozen=True, slots=True)
class BuyRiskRequest:
    """Typed pre-trade inputs whose units must not be interchanged."""

    trading_date: date
    requested_quantity: int
    price: float
    equity: float
    daily_volume: int
    board_lot: int


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    """End-of-day state evaluated by portfolio circuit breakers."""

    trading_date: date
    equity: float
    peak_equity: float
    previous_equity: float
    position_market_value: float
    position_cost: float
