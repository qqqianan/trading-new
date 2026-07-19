"""Typed portfolio-level risk inputs, limits, and governed decisions."""

from dataclasses import dataclass
from enum import StrEnum, unique

from ashare_lab.domain.market import Symbol
from ashare_lab.domain.risk import RiskEvent
from ashare_lab.portfolio.contracts import PortfolioTarget


@dataclass(frozen=True, slots=True)
class CurrentPosition:
    """Current marked portfolio weight retained for turnover and exit intent."""

    symbol: Symbol
    weight: float


@dataclass(frozen=True, slots=True)
class PortfolioMarketSnapshot:
    """Point-in-time capacity and eligibility evidence for one target symbol."""

    symbol: Symbol
    price: float
    daily_volume: int
    board_lot: int
    industry: str | None
    eligible_for_new_risk: bool


@dataclass(frozen=True, slots=True)
class PortfolioRiskConfig:
    """Frozen portfolio-level pre-trade policy."""

    max_position_weight: float = 0.05
    maximum_positions: int = 30
    minimum_cash_weight: float = 0.05
    maximum_turnover: float = 0.25
    maximum_volume_participation: float = 0.05
    maximum_industry_weight: float = 0.20
    maximum_concentration: float = 0.05


@dataclass(frozen=True, slots=True)
class PortfolioRiskRequest:
    """Target, current state, and PIT market evidence assessed together."""

    target: PortfolioTarget
    current_positions: tuple[CurrentPosition, ...]
    market: tuple[PortfolioMarketSnapshot, ...]
    equity: float


@unique
class PortfolioResearchStatus(StrEnum):
    """Whether complete portfolio governance evidence is available."""

    DRAFT = "DRAFT"
    VALIDATION_ELIGIBLE = "VALIDATION_ELIGIBLE"


@dataclass(frozen=True, slots=True)
class PortfolioRiskDecision:
    """Risk-governed target with complete resize/reject evidence."""

    target: PortfolioTarget
    events: tuple[RiskEvent, ...]
    turnover: float
    concentration: float
    status: PortfolioResearchStatus
