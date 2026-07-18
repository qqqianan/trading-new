"""Read-only Mongo adapter for weekly universe materialization evidence."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ashare_lab.research.universe.mongo_contracts import (
    UniverseCalendarConflictError,
    UniverseDatabase,
    UniverseEvidence,
    UniverseMarketConflictError,
    UniverseReaderError,
)
from ashare_lab.research.universe.mongo_documents import (
    DAILY_FIELDS,
    EVENT_FIELDS,
    CalendarDocument,
    ParsedMarketObservation,
    daily_snapshot,
    market_observation,
    parse_date,
    security_event,
)

if TYPE_CHECKING:
    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.universe import SecurityEvent
    from ashare_lab.research.universe.models import UniverseMarketObservation

_SHANGHAI = ZoneInfo("Asia/Shanghai")


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
        states: dict[str, int] = {}
        for item in parsed:
            if item.quality_status != "ACCEPTED" or item.schema_manifest_id != schema_manifest_id:
                continue
            previous = states.get(item.cal_date)
            if previous is not None and previous != item.is_open:
                raise UniverseCalendarConflictError(item.cal_date)
            states[item.cal_date] = item.is_open
        return tuple(sorted(parse_date(day) for day, is_open in states.items() if is_open == 1))

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
        snapshot_ids = self._daily_snapshot_ids(start_date, end_date, schema_manifest_id)
        if not snapshot_ids:
            return ()
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "quality_status": "ACCEPTED",
            "source_snapshot_id": {"$in": list(snapshot_ids)},
            "trade_date": {"$gte": _date_string(start_date), "$lte": _date_string(end_date)},
        }
        projection: BsonDocument = dict.fromkeys(DAILY_FIELDS, 1)
        parsed = tuple(
            market_observation(document)
            for document in self._database["canonical_daily_bar"].find(query, projection)
        )
        qualified = tuple(
            item
            for item in parsed
            if item.observation.quality_status == "ACCEPTED"
            and item.schema_manifest_id == schema_manifest_id
        )
        return _fold_market_replays(qualified)

    def _daily_snapshot_ids(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[str, ...]:
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "status": "ACCEPTED",
            "endpoint": "daily",
        }
        projection: BsonDocument = {
            "snapshot_id": 1,
            "endpoint": 1,
            "request_params_canonical": 1,
            "schema_manifest_id": 1,
            "status": 1,
        }
        parsed = tuple(
            daily_snapshot(document)
            for document in self._database["meta_source_snapshots"].find(query, projection)
        )
        return tuple(
            sorted(
                snapshot_id
                for snapshot_id, trade_date, observed_schema, status in parsed
                if start_date <= trade_date <= end_date
                and observed_schema == schema_manifest_id
                and status == "ACCEPTED"
            )
        )


def _date_string(value: date) -> str:
    return value.strftime("%Y%m%d")


def _fold_market_replays(
    parsed: tuple[ParsedMarketObservation, ...],
) -> tuple[UniverseMarketObservation, ...]:
    folded: dict[tuple[str, date], ParsedMarketObservation] = {}
    for item in parsed:
        key = (item.observation.symbol, item.observation.trading_date)
        previous = folded.get(key)
        if previous is not None and previous.material_identity != item.material_identity:
            raise UniverseMarketConflictError(*key)
        if (
            previous is None
            or item.observation.source_artifact_id < previous.observation.source_artifact_id
        ):
            folded[key] = item
    return tuple(folded[key].observation for key in sorted(folded))
