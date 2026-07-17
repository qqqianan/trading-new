"""Orchestrate canonical universe sources into persisted PIT events."""

from __future__ import annotations

import datetime as dt  # noqa: TC003 - Pydantic resolves this runtime annotation.
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, TypeAdapter
from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import CanonicalRecord, canonicalize_batch
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.universe import SecurityEvent, SecurityEventType
from ashare_lab.data.universe_builder import (
    build_first_trade_event,
    build_lifecycle_events,
    build_name_status_event,
)
from ashare_lab.data.universe_store import MongoUniverseEventStore, UniverseEventWriteResult

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.sync_service import SyncResult

_DAILY_SCHEMA_PATH = Path("schemas/tushare_p0_v1.json")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _StoredDailySource(BaseModel):
    """Parse the canonical fields needed for conservative first-trade evidence."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    record_id: str
    schema_manifest_id: str
    source_snapshot_id: str
    source_row_sha256: str
    transform_name: str
    transform_version: str
    event_time: dt.datetime
    available_at: dt.datetime
    ingested_at: dt.datetime
    quality_status: str
    quality_report_id: str
    ts_code: str
    trade_date: str


def build_universe_events(
    registry: SchemaRegistry,
    results: tuple[SyncResult, ...],
) -> tuple[SecurityEvent, ...]:
    """Transform only governed canonical source batches into PIT transitions."""
    events: list[SecurityEvent] = []
    for result in results:
        endpoint = result.batch.snapshot.endpoint
        schema = registry.endpoint(endpoint)
        canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
        match endpoint:
            case "stock_basic":
                for record in canonical.records:
                    events.extend(build_lifecycle_events(record))
            case "namechange":
                events.extend(build_name_status_event(record) for record in canonical.records)
            case _:
                detail = f"unsupported universe source endpoint: {endpoint}"
                raise SchemaContractError(detail)
    return tuple(events)


def persist_universe_results(
    registry: SchemaRegistry,
    results: tuple[SyncResult, ...],
) -> UniverseEventWriteResult:
    """Build and persist events through the isolated MongoDB adapter."""
    settings = DataSettings()
    events = build_universe_events(registry, results)
    daily_registry = SchemaRegistry.load(_DAILY_SCHEMA_PATH)
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
        tz_aware=True,
        tzinfo=_SHANGHAI,
    ) as mongo:
        store = MongoUniverseEventStore(mongo, settings.mongodb_database)
        fallback = _first_trade_fallbacks(
            mongo[settings.mongodb_database],
            daily_registry,
            registry,
            events,
        )
        return store.write(events + fallback)


def _first_trade_fallbacks(
    database: Database[BsonDocument],
    daily_registry: SchemaRegistry,
    universe_registry: SchemaRegistry,
    events: tuple[SecurityEvent, ...],
) -> tuple[SecurityEvent, ...]:
    listed_codes = {
        event.ts_code for event in events if event.event_type is SecurityEventType.LISTED
    }
    persisted_codes = TypeAdapter(list[str]).validate_python(
        database["pit_security_events"].distinct(
            "ts_code",
            {
                "schema_manifest_id": universe_registry.manifest_id,
                "quality_status": "ACCEPTED",
                "event_type": {"$in": ["LISTED", "FIRST_TRADED"]},
            },
        )
    )
    listed_codes.update(persisted_codes)
    collection = database["canonical_daily_bar"]
    daily_filter: BsonDocument = {
        "schema_manifest_id": daily_registry.manifest_id,
        "quality_status": "ACCEPTED",
    }
    daily_codes = TypeAdapter(list[str]).validate_python(
        collection.distinct("ts_code", daily_filter)
    )
    fallback: list[SecurityEvent] = []
    for ts_code in sorted(set(daily_codes) - listed_codes):
        document = collection.find_one(
            {**daily_filter, "ts_code": ts_code},
            sort=[("trade_date", 1)],
        )
        if document is None:
            continue
        source = _daily_source_record(_StoredDailySource.model_validate(document))
        fallback.append(build_first_trade_event(source, universe_registry.manifest_id))
    return tuple(fallback)


def _daily_source_record(source: _StoredDailySource) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=source.record_id,
        schema_manifest_id=source.schema_manifest_id,
        source_snapshot_id=source.source_snapshot_id,
        source_row_sha256=source.source_row_sha256,
        transform_name=source.transform_name,
        transform_version=source.transform_version,
        event_time=source.event_time,
        available_at=source.available_at,
        ingested_at=source.ingested_at,
        quality_status=source.quality_status,
        quality_report_id=source.quality_report_id,
        business_fields=(("ts_code", source.ts_code), ("trade_date", source.trade_date)),
    )
