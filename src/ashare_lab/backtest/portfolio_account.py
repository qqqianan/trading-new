"""Mutable portfolio account and A-share open execution rules."""

from dataclasses import dataclass, field
from math import floor
from typing import TYPE_CHECKING

from ashare_lab.backtest.portfolio_contracts import (
    ExecutionBatch,
    OrderBlockReason,
    OrderStatus,
    PortfolioOrderRecord,
    PortfolioPosition,
    PortfolioSession,
)
from ashare_lab.backtest.portfolio_execution import (
    BOARD_LOT,
    ExecutionRequest,
    OrderOutcome,
    OrderRequest,
    blocked_outcome,
    retained_exit_event,
)
from ashare_lab.backtest.portfolio_positions import PositionState
from ashare_lab.backtest.portfolio_settlement import settle_buy, settle_sell
from ashare_lab.domain.market import MarketBar, Symbol
from ashare_lab.domain.trading import Trade, TradeSide

if TYPE_CHECKING:
    from ashare_lab.domain.risk import RiskEvent


@dataclass(slots=True)
class PortfolioAccount:
    """Mutable cash and tax-lot ledger scoped to one engine run."""

    cash: float
    positions: dict[Symbol, PositionState] = field(default_factory=dict)
    total_fees: float = 0.0

    def mark(self, session: PortfolioSession) -> tuple[float, float]:
        """Update available closes and return market value and equity."""
        bars = {bar.symbol: bar for bar in session.bars}
        for symbol, position in self.positions.items():
            bar = bars.get(symbol)
            if bar is not None:
                position.last_price = bar.close
        market_value = sum(item.shares * item.last_price for item in self.positions.values())
        return market_value, self.cash + market_value

    def weights(self, equity: float) -> dict[Symbol, float]:
        """Return marked current weights for the mandatory risk request."""
        return {
            symbol: position.shares * position.last_price / equity
            for symbol, position in self.positions.items()
        }

    def snapshots(self) -> tuple[PortfolioPosition, ...]:
        """Freeze ending positions in stable symbol order."""
        return tuple(
            PortfolioPosition(
                symbol,
                item.shares,
                item.total_cost,
                max(lot.acquired_on for lot in item.lots),
                item.last_price,
            )
            for symbol, item in sorted(self.positions.items(), key=lambda value: str(value[0]))
        )

    def execute(self, request: ExecutionRequest) -> ExecutionBatch:
        """Reconcile one retained target at the session open, sells before buys."""
        bars = {bar.symbol: bar for bar in request.session.bars}
        open_equity = self.cash + sum(
            position.shares * (bars[symbol].open if symbol in bars else position.last_price)
            for symbol, position in self.positions.items()
        )
        symbols = set(request.weights) | set(self.positions)
        trades: list[Trade] = []
        orders: list[PortfolioOrderRecord] = []
        events: list[RiskEvent] = []
        for side in (TradeSide.SELL, TradeSide.BUY):
            for symbol in sorted(symbols, key=str):
                outcome = self._reconcile_symbol(
                    request,
                    symbol,
                    side,
                    bars.get(symbol),
                    open_equity,
                )
                if outcome is None:
                    continue
                orders.append(outcome.order)
                if outcome.trade is not None:
                    trades.append(outcome.trade)
                if outcome.risk_event is not None:
                    events.append(outcome.risk_event)
        has_pending = any(item.status is not OrderStatus.FILLED for item in orders)
        return ExecutionBatch(tuple(trades), tuple(orders), tuple(events), has_pending)

    def _reconcile_symbol(
        self,
        request: ExecutionRequest,
        symbol: Symbol,
        side: TradeSide,
        bar: MarketBar | None,
        equity: float,
    ) -> OrderOutcome | None:
        position = self.positions.get(symbol)
        current = position.shares if position is not None else 0
        if bar is None:
            is_missing_sell = side is TradeSide.SELL and current > 0
            is_missing_buy = side is TradeSide.BUY and request.weights.get(symbol, 0.0) > 0
            if is_missing_sell or is_missing_buy:
                order = OrderRequest(
                    request.session.trading_date,
                    symbol,
                    side,
                    current,
                    bar,
                    0,
                    equity * request.policy.minimum_cash_weight,
                    request.policy,
                    request.risk_exit,
                )
                return blocked_outcome(order, OrderBlockReason.MISSING_BAR)
            return None
        desired = (
            floor(request.weights.get(symbol, 0.0) * equity / bar.open / BOARD_LOT) * BOARD_LOT
        )
        delta = desired - current
        if (side is TradeSide.SELL and delta >= 0) or (side is TradeSide.BUY and delta <= 0):
            return None
        sellable = position.sellable(request.session.trading_date) if position is not None else 0
        order = OrderRequest(
            request.session.trading_date,
            symbol,
            side,
            abs(delta),
            bar,
            sellable,
            equity * request.policy.minimum_cash_weight,
            request.policy,
            request.risk_exit,
        )
        return self._execute_order(order)

    def _execute_order(self, order: OrderRequest) -> OrderOutcome:
        reason = order.block_reason()
        if reason is not None:
            return blocked_outcome(order, reason)
        bar = order.bar
        if bar is None:
            return blocked_outcome(order, OrderBlockReason.MISSING_BAR)
        capacity = floor(bar.volume * order.policy.participation / BOARD_LOT) * BOARD_LOT
        available = order.requested if order.side is TradeSide.BUY else order.sellable
        quantity = min(order.requested, capacity, available)
        if quantity < BOARD_LOT:
            reason = (
                OrderBlockReason.T_PLUS_ONE
                if order.side is TradeSide.SELL and order.sellable == 0
                else OrderBlockReason.VOLUME_CAPACITY
            )
            return blocked_outcome(order, reason)
        settlement = (
            settle_sell(self.positions, order, bar, quantity)
            if order.side is TradeSide.SELL
            else settle_buy(self.cash, self.positions, order, bar, quantity)
        )
        if settlement is None:
            return blocked_outcome(order, OrderBlockReason.INSUFFICIENT_CASH)
        trade = settlement.trade
        self.cash += settlement.cash_delta
        self.total_fees += settlement.fees
        if trade.quantity == order.requested:
            reason = OrderBlockReason.FILLED
        elif order.side is TradeSide.SELL and order.sellable < order.requested:
            reason = OrderBlockReason.T_PLUS_ONE
        elif trade.quantity < quantity:
            reason = OrderBlockReason.INSUFFICIENT_CASH
        else:
            reason = OrderBlockReason.VOLUME_CAPACITY
        status = OrderStatus.FILLED if trade.quantity == order.requested else OrderStatus.PARTIAL
        record = PortfolioOrderRecord(
            order.trading_date,
            order.symbol,
            order.side,
            order.requested,
            trade.quantity,
            status,
            reason,
            order.risk_exit,
            trade.quantity / bar.volume,
        )
        event = retained_exit_event(order, reason) if status is OrderStatus.PARTIAL else None
        return OrderOutcome(record, trade, event)
