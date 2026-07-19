"""Per-symbol tax lots for exact A-share T+1 and cost basis."""

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class TaxLot:
    """Mutable acquisition lot owned by one account simulation."""

    shares: int
    total_cost: float
    acquired_on: date


@dataclass(slots=True)
class PositionState:
    """Mutable per-symbol lots and latest mark owned by one run."""

    lots: list[TaxLot]
    last_price: float

    @property
    def shares(self) -> int:
        """Return total shares across acquisition lots."""
        return sum(item.shares for item in self.lots)

    @property
    def total_cost(self) -> float:
        """Return remaining fee-inclusive cost basis."""
        return sum(item.total_cost for item in self.lots)

    def sellable(self, trading_date: date) -> int:
        """Return shares acquired before the current trading date."""
        return sum(item.shares for item in self.lots if item.acquired_on < trading_date)


def consume_lots(position: PositionState, quantity: int, trading_date: date) -> float:
    """Consume sellable lots FIFO and return their proportional cost basis."""
    remaining = quantity
    cost_basis = 0.0
    for lot in position.lots:
        if remaining == 0 or lot.acquired_on >= trading_date:
            continue
        consumed = min(remaining, lot.shares)
        consumed_cost = lot.total_cost * consumed / lot.shares
        lot.shares -= consumed
        lot.total_cost -= consumed_cost
        remaining -= consumed
        cost_basis += consumed_cost
    position.lots[:] = [item for item in position.lots if item.shares > 0]
    return cost_basis
