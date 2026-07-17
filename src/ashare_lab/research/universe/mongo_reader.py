"""Read-only Mongo adapter for weekly universe materialization evidence."""

from collections.abc import Iterable
from datetime import date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.universe import SecurityEvent
from ashare_lab.research.universe.models import UniverseMarketObservation
from ashare_lab.research.universe.mongo_documents import (
    DAILY_FIELDS,
    EVENT_FIELDS,
    CalendarDocument,
    market_observation,
    parse_date,
    security_event,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


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


class MongoUniversePanelReader:
    """Load exact-schema accepted calendar, lifecycle, and daily evidence."""

    def __init__(self, database: UniverseDatabase) -> None:
        """Bind without owning or mutating the Mongo connection."""
        if database.name != "ashare_quant":
            raise UniverseReaderError(database.name)
        self._database = database

    def read(
        self,
        start_date: date,
        end_date: date,
        market_schema_manifest_id: str,
        universe_schema_manifest_id: str,
    ) -> UniverseEvidence:
        """Load one closed interval without mixing old schema versions."""
        return UniverseEvidence(
            open_dates=self.open_dates(
                start_date,
                end_date,
                market_schema_manifest_id,
            ),
            events=self.events(end_date, universe_schema_manifest_id),
            observations=self.observations(
                start_date,
                end_date,
                market_schema_manifest_id,
            ),
        )

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        """Load accepted open sessions from one exact market schema."""
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "quality_status": "ACCEPTED",
            "exchange": "SSE",
            "is_open": 1,
            "cal_date": {"$gte": _date_string(start_date), "$lte": _date_string(end_date)},
        }
        projection: BsonDocument = {
            "cal_date": 1,
            "is_open": 1,
            "quality_status": 1,
            "schema_manifest_id": 1,
        }
        parsed = tuple(
            CalendarDocument.model_validate(document)
            for document in self._database["canonical_trade_calendar"].find(query, projection)
        )
        return tuple(
            sorted(
                parse_date(item.cal_date)
                for item in parsed
                if item.is_open == 1
                and item.quality_status == "ACCEPTED"
                and item.schema_manifest_id == schema_manifest_id
            )
        )

    def events(
        self,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[SecurityEvent, ...]:
        """Load accepted lifecycle events visible by the interval end."""
        cutoff = datetime.combine(end_date, time.max, _SHANGHAI)
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "quality_status": "ACCEPTED",
            "effective_at": {"$lte": cutoff},
            "available_at": {"$lte": cutoff},
        }
        projection: BsonDocument = dict.fromkeys(EVENT_FIELDS, 1)
        events = tuple(
            security_event(document)
            for document in self._database["pit_security_events"].find(query, projection)
        )
        return tuple(
            event
            for event in events
            if event.quality_status == "ACCEPTED" and event.schema_manifest_id == schema_manifest_id
        )

    def observations(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[UniverseMarketObservation, ...]:
        """Load accepted daily admission observations for one bounded batch."""
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "quality_status": "ACCEPTED",
            "trade_date": {"$gte": _date_string(start_date), "$lte": _date_string(end_date)},
        }
        projection: BsonDocument = dict.fromkeys(DAILY_FIELDS, 1)
        parsed = tuple(
            market_observation(document)
            for document in self._database["canonical_daily_bar"].find(query, projection)
        )
        return tuple(
            observation
            for observation, observed_schema in parsed
            if observation.quality_status == "ACCEPTED" and observed_schema == schema_manifest_id
        )


def _date_string(value: date) -> str:
    return value.strftime("%Y%m%d")
