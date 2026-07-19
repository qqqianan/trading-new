"""Immutable order requests and blocked-execution audit construction."""

from dataclasses import dataclass
from datetime import date
from typing import Final

from ashare_lab.backtest.costs import ChinaACommission
from ashare_lab.backtest.portfolio_contracts import (
    OrderBlockReason,
    OrderStatus,
    PortfolioOrderRecord,
    PortfolioSession,
)
from ashare_lab.domain.market import MarketBar, Symbol
from ashare_lab.domain.risk import RiskAction, RiskEvent, RiskRule
from ashare_lab.domain.trading import Trade, TradeSide

BOARD_LOT: Final = 100


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """Execution limits and costs reused by every order attempt."""

    participation: float
    slippage: float
    minimum_cash_weight: float
    costs: ChinaACommission


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """One retained target reconciled at a session open."""

    session: PortfolioSession
    weights: dict[Symbol, float]
    policy: ExecutionPolicy
    risk_exit: bool


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """One symbol-side execution attempt with exact T+1 capacity."""

    trading_date: date
    symbol: Symbol
    side: TradeSide
    requested: int
    bar: MarketBar | None
    sellable: int
    cash_reserve: float
    policy: ExecutionPolicy
    risk_exit: bool

    def block_reason(self) -> OrderBlockReason | None:
        """Return the market-state blocker before sizing capacity."""
        if self.bar is None:
            return OrderBlockReason.MISSING_BAR
        if self.bar.is_suspended:
            return OrderBlockReason.SUSPENDED
        if self.side is TradeSide.BUY and self.bar.open >= self.bar.limit_up - 1e-8:
            return OrderBlockReason.LIMIT_UP
        if self.side is TradeSide.SELL and self.bar.open <= self.bar.limit_down + 1e-8:
            return OrderBlockReason.LIMIT_DOWN
        return None


@dataclass(frozen=True, slots=True)
class OrderOutcome:
    """Order audit record with optional fill and risk event."""

    order: PortfolioOrderRecord
    trade: Trade | None
    risk_event: RiskEvent | None


def blocked_outcome(request: OrderRequest, reason: OrderBlockReason) -> OrderOutcome:
    """Retain a blocked order and disclose blocked risk exits."""
    event = None
    if request.risk_exit and request.side is TradeSide.SELL:
        event = RiskEvent(
            request.trading_date,
            RiskRule.EXIT_BLOCKED,
            RiskAction.RETRY_EXIT,
            request.bar.open if request.bar is not None else 0.0,
            request.bar.limit_down if request.bar is not None else 0.0,
            f"risk exit blocked by {reason.value}; order retained",
            request.symbol,
        )
    order = PortfolioOrderRecord(
        request.trading_date,
        request.symbol,
        request.side,
        request.requested,
        0,
        OrderStatus.PENDING,
        reason,
        request.risk_exit,
        0.0,
    )
    return OrderOutcome(order, None, event)


def retained_exit_event(request: OrderRequest, reason: OrderBlockReason) -> RiskEvent | None:
    """Disclose the unfilled remainder of a partially filled risk exit."""
    if not request.risk_exit or request.side is not TradeSide.SELL:
        return None
    bar = request.bar
    return RiskEvent(
        request.trading_date,
        RiskRule.EXIT_BLOCKED,
        RiskAction.RETRY_EXIT,
        bar.open if bar is not None else 0.0,
        bar.limit_down if bar is not None else 0.0,
        f"risk exit partially filled due to {reason.value}; remainder retained",
        request.symbol,
    )
