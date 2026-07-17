from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pymongo import UpdateOne

from ashare_lab.data.universe import SecurityEvent, SecurityEventType
from ashare_lab.data.universe_store import (
    MongoUniverseEventStore,
    security_event_from_document,
    universe_event_document,
    universe_lineage_document,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeBulkResult:
    """Return one inserted event from a fake bulk write."""

    upserted_count = 1


class FakeCollection:
    """Capture bulk persistence calls by collection."""

    def __init__(self) -> None:
        self.bulk_calls = 0

    def bulk_write(
        self,
        operations: list[UpdateOne],
        *,
        ordered: bool,
    ) -> FakeBulkResult:
        assert operations
        assert ordered is False
        self.bulk_calls += 1
        return FakeBulkResult()


class FakeDatabase:
    """Provide event, quality, and lineage collections."""

    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def test_universe_event_document_excludes_future_outcome_fields() -> None:
    # Given: one accepted historical listing event.
    event = _event()

    # When: it crosses the Mongo serialization boundary.
    document = universe_event_document(event)

    # Then: only the transition is exposed, never a future delisting outcome.
    assert document["event_type"] == "LISTED"
    assert document["effective_at"] == event.effective_at
    assert "delist_date" not in document
    assert "list_status" not in document


def test_universe_event_document_round_trips_through_typed_boundary() -> None:
    # Given: a serialized accepted PIT event.
    event = _event()
    document = universe_event_document(event)

    # When: Mongo data is parsed back into the closed event contract.
    parsed = security_event_from_document(document)

    # Then: the event identity and time semantics remain exact.
    assert parsed == event


def test_mongo_naive_utc_datetimes_restore_shanghai_event_times() -> None:
    # Given: BSON-style datetimes returned as timezone-free UTC values.
    event = _event()
    document = universe_event_document(event)
    for field in ("effective_at", "available_at", "ingested_at"):
        value = document[field]
        assert isinstance(value, datetime)
        document[field] = value.astimezone(UTC).replace(tzinfo=None)

    # When: the Mongo document crosses the typed read boundary.
    parsed = security_event_from_document(document)

    # Then: every timestamp recovers its original Shanghai instant and timezone.
    assert parsed.effective_at == event.effective_at
    assert parsed.available_at == event.available_at
    assert parsed.ingested_at == event.ingested_at


def test_universe_lineage_maps_event_fields_to_exact_raw_fields() -> None:
    # Given: an event derived from one stock-basic Raw row.
    event = _event()

    # When: its field-level lineage document is produced.
    lineage = universe_lineage_document(event, "a" * 40)

    # Then: the transition and identity map to explicit provider fields.
    mappings = lineage["field_mappings"]
    assert isinstance(mappings, list)
    assert "pit_security_events.ts_code<-raw_tushare_stock_basic.payload.ts_code" in mappings
    assert "pit_security_events.effective_at<-raw_tushare_stock_basic.payload.list_date" in mappings


def test_universe_store_atomically_persists_event_quality_and_lineage_evidence() -> None:
    # Given: a Mongo adapter backed by isolated fake collections.
    store = MongoUniverseEventStore.__new__(MongoUniverseEventStore)
    database = FakeDatabase()
    store.__dict__["_database"] = database

    # When: one accepted event is written.
    result = store.write((_event(),))

    # Then: event, quality, and lineage evidence are all persisted.
    assert result.event_count == 1
    assert result.inserted_count == 1
    assert database["pit_security_events"].bulk_calls == 1
    assert database["meta_quality_reports"].bulk_calls == 1
    assert database["meta_lineage_edges"].bulk_calls == 1


def _event() -> SecurityEvent:
    effective = datetime(2020, 1, 2, 9, 25, tzinfo=SHANGHAI)
    ingested = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    return SecurityEvent(
        event_id="universe_event_abc",
        ts_code="000001.SZ",
        event_type=SecurityEventType.LISTED,
        effective_at=effective,
        available_at=effective,
        ingested_at=ingested,
        name=None,
        is_st=None,
        source_endpoint="stock_basic",
        source_snapshot_id="snap_abc",
        source_row_sha256="a" * 64,
        input_schema_manifest_id="schema_abc",
        schema_manifest_id="schema_abc",
        transform_name="security_master_to_pit_events",
        transform_version="1.0.0",
        quality_status="ACCEPTED",
        quality_report_id="quality_abc",
    )
