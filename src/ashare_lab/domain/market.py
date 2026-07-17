"""Market data contracts shared by providers and research services."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique
from typing import NewType, Protocol

Symbol = NewType("Symbol", str)


@unique
class PriceBasis(StrEnum):
    """Explicit price adjustment basis."""

    RAW = "raw"
    FORWARD_ADJUSTED = "forward_adjusted"
    BACKWARD_ADJUSTED = "backward_adjusted"


@dataclass(frozen=True, slots=True)
class Instrument:
    """A tradable A-share instrument."""

    symbol: Symbol
    name: str
    exchange: str
    board: str


@dataclass(frozen=True, slots=True)
class MarketBar:
    """A daily bar with raw execution limits."""

    symbol: Symbol
    trading_date: date
    available_at: datetime
    price_basis: PriceBasis
    open: float
    high: float
    low: float
    close: float
    volume: int
    previous_close: float
    limit_up: float
    limit_down: float
    is_suspended: bool


class MarketDataProvider(Protocol):
    """Port implemented by demo and future real-market adapters."""

    @property
    def source_name(self) -> str:
        """Return the user-visible source identifier."""
        ...

    def list_instruments(self) -> tuple[Instrument, ...]:
        """List instruments available for research."""
        ...

    def history(self, symbol: Symbol) -> tuple[MarketBar, ...]:
        """Load ordered daily history for one instrument."""
        ...
