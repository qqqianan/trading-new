"""Pre-trade sizing and in-position circuit breakers."""

from datetime import date
from math import floor

from ashare_lab.domain.risk import (
    BuyRiskRequest,
    RiskAction,
    RiskEvent,
    RiskLimits,
    RiskRule,
    RiskSizingDecision,
    RiskSnapshot,
)


class RiskEngine:
    """Apply immutable limits independently from strategy intent."""

    def __init__(self, limits: RiskLimits) -> None:
        """Bind a run to one explicit risk policy."""
        self._limits = limits

    @property
    def limits(self) -> RiskLimits:
        """Expose the active immutable policy for reporting."""
        return self._limits

    def size_buy(self, request: BuyRiskRequest) -> RiskSizingDecision:
        """Cap a requested buy by position, cash, and liquidity limits."""
        position_cap = self._lot_quantity(
            request.equity * self._limits.max_position_weight,
            request.price,
            request.board_lot,
        )
        cash_cap = self._lot_quantity(
            request.equity * (1.0 - self._limits.minimum_cash_weight),
            request.price,
            request.board_lot,
        )
        volume_cap = (
            floor(request.daily_volume * self._limits.max_volume_participation / request.board_lot)
            * request.board_lot
        )
        caps = (
            (RiskRule.MAX_POSITION_WEIGHT, position_cap, self._limits.max_position_weight),
            (RiskRule.MINIMUM_CASH_WEIGHT, cash_cap, self._limits.minimum_cash_weight),
            (RiskRule.VOLUME_PARTICIPATION, volume_cap, self._limits.max_volume_participation),
        )
        binding_rule, adjusted, limit = min(caps, key=lambda item: item[1])
        adjusted = min(request.requested_quantity, adjusted)
        if adjusted >= request.requested_quantity:
            return RiskSizingDecision(quantity=request.requested_quantity, events=())
        action = RiskAction.REJECT if adjusted == 0 else RiskAction.RESIZE
        event = RiskEvent(
            trading_date=request.trading_date,
            rule=binding_rule,
            action=action,
            observed=float(request.requested_quantity),
            limit=limit,
            message=(f"requested {request.requested_quantity} shares, risk-adjusted to {adjusted}"),
        )
        return RiskSizingDecision(quantity=adjusted, events=(event,))

    def assess_close(self, snapshot: RiskSnapshot) -> tuple[RiskEvent, ...]:
        """Trigger the highest-priority end-of-day circuit breaker."""
        drawdown = snapshot.equity / snapshot.peak_equity - 1.0
        if drawdown <= -self._limits.max_drawdown:
            return (
                self._circuit_event(
                    snapshot.trading_date,
                    RiskRule.MAX_DRAWDOWN,
                    drawdown,
                    self._limits.max_drawdown,
                ),
            )
        daily_return = snapshot.equity / snapshot.previous_equity - 1.0
        if daily_return <= -self._limits.max_daily_loss:
            return (
                self._circuit_event(
                    snapshot.trading_date,
                    RiskRule.MAX_DAILY_LOSS,
                    daily_return,
                    self._limits.max_daily_loss,
                ),
            )
        position_return = snapshot.position_market_value / snapshot.position_cost - 1.0
        if position_return <= -self._limits.max_position_loss:
            return (
                self._circuit_event(
                    snapshot.trading_date,
                    RiskRule.MAX_POSITION_LOSS,
                    position_return,
                    self._limits.max_position_loss,
                ),
            )
        return ()

    @staticmethod
    def _lot_quantity(notional: float, price: float, board_lot: int) -> int:
        return floor(notional / price / board_lot) * board_lot

    @staticmethod
    def _circuit_event(
        trading_date: date,
        rule: RiskRule,
        observed: float,
        limit: float,
    ) -> RiskEvent:
        return RiskEvent(
            trading_date=trading_date,
            rule=rule,
            action=RiskAction.HALT_AND_LIQUIDATE,
            observed=observed,
            limit=limit,
            message=f"{rule.value} breached: observed {observed:.4f}, limit {limit:.4f}",
        )
