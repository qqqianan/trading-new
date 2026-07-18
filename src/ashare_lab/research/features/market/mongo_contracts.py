"""Read capabilities and quality outcomes for governed market bundles."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.research.features.market.models import MarketFactorObservation

type MarketKey = tuple[str, date]


class MarketCollection(Protocol):
    """Minimal read capability required from one Mongo collection."""

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> Iterable[BsonDocument]:
        """Return documents matching one governed query."""
        ...


class MarketDatabase(Protocol):
    """Minimal named database capability used by the reader."""

    name: str

    def __getitem__(self, name: str) -> MarketCollection:
        """Return a governed collection by name."""
        ...


@dataclass(frozen=True, slots=True)
class MarketBundleRejection:
    """One daily anchor that cannot become a factor observation."""

    symbol: str
    trading_date: date
    reason: str


@dataclass(frozen=True, slots=True)
class MarketBundleReadResult:
    """Complete observations plus explicit incomplete-bundle evidence."""

    observations: tuple[MarketFactorObservation, ...]
    rejections: tuple[MarketBundleRejection, ...]
    suspended_keys: tuple[MarketKey, ...]


class MarketBundleConflictError(Exception):
    """One natural key carries materially different accepted facts."""

    __slots__ = ("collection", "key")

    def __init__(self, collection: str, key: MarketKey) -> None:
        """Record the conflicting collection and natural key."""
        super().__init__()
        self.collection = collection
        self.key = key

    def __str__(self) -> str:
        """Return the stable conflict rule and key."""
        return f"market_bundle_conflict: {self.collection}:{self.key[0]}:{self.key[1]:%Y%m%d}"


class MarketBundleReaderError(Exception):
    """The reader is bound outside the governed database."""

    __slots__ = ("database_name",)

    def __init__(self, database_name: str) -> None:
        """Record only the rejected database name."""
        super().__init__()
        self.database_name = database_name

    def __str__(self) -> str:
        """Return the database isolation failure."""
        return f"market bundle reader requires ashare_quant, got {self.database_name}"
