"""Read capabilities and typed failures for Mongo universe evidence."""

from collections.abc import Iterable
from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.universe import SecurityEvent
from ashare_lab.research.universe.models import UniverseMarketObservation


class UniverseCollection(Protocol):
    """Minimal read capability used from one Mongo collection."""

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> Iterable[BsonDocument]:
        """Return documents matching one governed query."""
        ...


class UniverseDatabase(Protocol):
    """Minimal database capability required by the read-only adapter."""

    name: str

    def __getitem__(self, name: str) -> UniverseCollection:
        """Return a named governed collection."""
        ...


class UniverseEvidence(BaseModel):
    """Validated bounded inputs for pure PIT panel construction."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    open_dates: tuple[date, ...]
    events: tuple[SecurityEvent, ...]
    observations: tuple[UniverseMarketObservation, ...]


class UniverseReaderError(Exception):
    """The reader is bound outside its governed database."""

    __slots__ = ("database_name",)

    def __init__(self, database_name: str) -> None:
        """Record only the rejected database name, never credentials."""
        super().__init__()
        self.database_name = database_name

    def __str__(self) -> str:
        """Return the fixed database isolation failure."""
        return f"universe reader requires ashare_quant, got {self.database_name}"


class UniverseCalendarConflictError(Exception):
    """One natural calendar key carries conflicting accepted states."""

    __slots__ = ("cal_date",)

    def __init__(self, cal_date: str) -> None:
        """Record the ambiguous provider calendar date."""
        super().__init__()
        self.cal_date = cal_date

    def __str__(self) -> str:
        """Return the stable conflict rule and affected date."""
        return f"calendar_natural_key_conflict: {self.cal_date}"


class UniverseMarketConflictError(Exception):
    """One symbol-date key carries conflicting accepted market facts."""

    __slots__ = ("symbol", "trading_date")

    def __init__(self, symbol: str, trading_date: date) -> None:
        """Record the ambiguous natural market key."""
        super().__init__()
        self.symbol = symbol
        self.trading_date = trading_date

    def __str__(self) -> str:
        """Return the stable conflict rule and natural key."""
        return f"market_natural_key_conflict: {self.symbol}:{self.trading_date:%Y%m%d}"
