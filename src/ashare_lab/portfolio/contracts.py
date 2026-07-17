"""Portfolio targets kept separate from model predictions and broker orders."""

from dataclasses import dataclass
from datetime import date

from ashare_lab.domain.market import Symbol


@dataclass(frozen=True, slots=True)
class TargetPosition:
    """Desired weight for one security after portfolio construction."""

    symbol: Symbol
    weight: float
    score: float


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    """Dated portfolio intent that must still pass the risk engine."""

    decision_date: date
    model_id: str
    positions: tuple[TargetPosition, ...]
    cash_weight: float
