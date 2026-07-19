"""Fee-aware buy and sell settlement against portfolio tax lots."""

from dataclasses import dataclass

from ashare_lab.backtest.portfolio_execution import BOARD_LOT, OrderRequest
from ashare_lab.backtest.portfolio_positions import PositionState, TaxLot, consume_lots
from ashare_lab.domain.market import MarketBar, Symbol
from ashare_lab.domain.trading import Trade, TradeSide


@dataclass(frozen=True, slots=True)
class SettlementResult:
    """One fill and its signed cash and fee effects."""

    trade: Trade
    cash_delta: float
    fees: float


def settle_buy(
    cash: float,
    positions: dict[Symbol, PositionState],
    order: OrderRequest,
    bar: MarketBar,
    quantity: int,
) -> SettlementResult | None:
    """Buy affordable board lots and append a new T+1 acquisition lot."""
    price = bar.open * (1.0 + order.policy.slippage)
    affordable = quantity
    charge = order.policy.costs.for_buy(affordable * price)
    while affordable > 0 and affordable * price + charge.total > cash - order.cash_reserve:
        affordable -= BOARD_LOT
        charge = order.policy.costs.for_buy(affordable * price)
    if affordable <= 0:
        return None
    notional = affordable * price
    total_cost = notional + charge.total
    position = positions.get(order.symbol)
    lot = TaxLot(affordable, total_cost, order.trading_date)
    if position is None:
        positions[order.symbol] = PositionState([lot], bar.open)
    else:
        position.lots.append(lot)
        position.last_price = bar.open
    trade = Trade(
        order.trading_date,
        order.symbol,
        TradeSide.BUY,
        affordable,
        price,
        notional,
        charge.commission,
        0.0,
        None,
    )
    return SettlementResult(trade, -total_cost, charge.total)


def settle_sell(
    positions: dict[Symbol, PositionState],
    order: OrderRequest,
    bar: MarketBar,
    quantity: int,
) -> SettlementResult:
    """Sell FIFO sellable lots and preserve fee-inclusive realized PnL."""
    position = positions[order.symbol]
    price = bar.open * (1.0 - order.policy.slippage)
    notional = quantity * price
    charge = order.policy.costs.for_sell(notional)
    cost_basis = consume_lots(position, quantity, order.trading_date)
    realized = notional - charge.total - cost_basis
    position.last_price = bar.open
    if position.shares == 0:
        del positions[order.symbol]
    trade = Trade(
        order.trading_date,
        order.symbol,
        TradeSide.SELL,
        quantity,
        price,
        notional,
        charge.commission,
        charge.stamp_duty,
        realized,
    )
    return SettlementResult(trade, notional - charge.total, charge.total)
