"""China A-share transaction cost model."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransactionCosts:
    """Separated costs for auditability."""

    commission: float
    stamp_duty: float

    @property
    def total(self) -> float:
        """Return all fees charged for the fill."""
        return self.commission + self.stamp_duty


@dataclass(frozen=True, slots=True)
class ChinaACommission:
    """Commission on both sides and stamp duty on sells."""

    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005

    def for_buy(self, notional: float) -> TransactionCosts:
        """Calculate buy-side costs without stamp duty."""
        commission = round(max(notional * self.commission_rate, self.minimum_commission), 2)
        return TransactionCosts(commission=commission, stamp_duty=0.0)

    def for_sell(self, notional: float) -> TransactionCosts:
        """Calculate sell-side commission and stamp duty."""
        commission = round(max(notional * self.commission_rate, self.minimum_commission), 2)
        return TransactionCosts(
            commission=commission,
            stamp_duty=round(notional * self.stamp_duty_rate, 2),
        )
