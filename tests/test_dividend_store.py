from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pymongo import MongoClient, UpdateOne

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.corporate_action_store import (
    MongoDividendEventStore,
    dividend_event_document,
    dividend_lineage_document,
)
from ashare_lab.data.corporate_actions import DividendEvent, DividendEventType

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeBulkResult:
    """Return one inserted document from a fake Mongo bulk write."""

    upserted_count = 1


class FakeCollection:
    """Capture bulk and singleton evidence writes."""

    def __init__(self) -> None:
        self.bulk_calls = 0
        self.update_calls = 0

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

    def update_one(
        self,
        query: dict[str, str],
        update: dict[str, dict[str, str | bool | list[str] | datetime]],
        *,
        upsert: bool,
    ) -> None:
        assert query
        assert update
        assert upsert is True
        self.update_calls += 1


class FakeDatabase:
    """Provide named in-memory collections to the dividend adapter."""

    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def test_plan_document_physically_excludes_implementation_dates() -> None:
    # Given: a proposal-stage dividend event.
    event = _event(DividendEventType.PLAN_ANNOUNCED)

    # When: it crosses the Mongo serialization boundary.
    document = dividend_event_document(event)

    # Then: implementation dates remain null rather than future-filled.
    assert document["record_date"] is None
    assert document["ex_date"] is None
    assert document["pay_date"] is None


def test_dividend_lineage_maps_stage_fields_to_exact_raw_columns() -> None:
    # Given: an implementation-stage event.
    event = _event(DividendEventType.IMPLEMENTATION_ANNOUNCED)

    # When: its field-level lineage is generated.
    lineage = dividend_lineage_document(event, "a" * 40)

    # Then: both the announcement clock and ex-date retain explicit source mappings.
    mappings = lineage["field_mappings"]
    assert isinstance(mappings, list)
    assert "pit_dividend_events.effective_at<-raw_tushare_dividend.payload.imp_ann_date" in mappings
    assert "pit_dividend_events.ex_date<-raw_tushare_dividend.payload.ex_date" in mappings


def test_empty_dividend_batch_still_persists_completion_evidence() -> None:
    # Given: an empty but governed canonical batch for one announcement date.
    store = MongoDividendEventStore.__new__(MongoDividendEventStore)
    database = FakeDatabase()
    store.__dict__["_database"] = database
    batch = _batch()

    # When: the PIT projection completes with no business events.
    result = store.write_batch(batch, ())

    # Then: batch quality and lineage prove the date ran without inventing an event.
    assert result.event_count == 0
    assert result.inserted_count == 0
    assert database["pit_dividend_events"].bulk_calls == 0
    assert database["meta_quality_reports"].update_calls == 1
    assert database["meta_lineage_edges"].update_calls == 1


def test_nonempty_dividend_batch_persists_event_quality_and_lineage() -> None:
    # Given: one implementation event and a governed canonical batch.
    store = MongoDividendEventStore.__new__(MongoDividendEventStore)
    database = FakeDatabase()
    store.__dict__["_database"] = database

    # When: the event projection is persisted.
    result = store.write_batch(
        _batch(),
        (_event(DividendEventType.IMPLEMENTATION_ANNOUNCED),),
    )

    # Then: the event and both immutable evidence documents are written together.
    assert result.inserted_count == 1
    assert database["pit_dividend_events"].bulk_calls == 1
    assert database["meta_quality_reports"].bulk_calls == 1
    assert database["meta_lineage_edges"].bulk_calls == 1


def test_dividend_store_rejects_nonisolated_database() -> None:
    # Given: a lazy Mongo client that performs no network connection.
    client = MongoClient[BsonDocument](connect=False)

    # When / Then: the adapter rejects any database outside ashare_quant.
    with pytest.raises(ValueError, match="restricted to ashare_quant"):
        MongoDividendEventStore(client, "tradingagentscn")
    client.close()


def _event(event_type: DividendEventType) -> DividendEvent:
    announced = datetime(2026, 5, 25, 18, 0, tzinfo=SHANGHAI)
    implementation = event_type is DividendEventType.IMPLEMENTATION_ANNOUNCED
    return DividendEvent(
        event_id=f"dividend_event_{event_type.value}",
        ts_code="000001.SZ",
        end_date="20251231",
        event_type=event_type,
        effective_at=announced,
        available_at=announced,
        ingested_at=datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI),
        div_proc="实施",
        stk_div=0.0,
        stk_bo_rate=0.0,
        stk_co_rate=0.0,
        cash_div=0.5,
        cash_div_tax=0.45,
        record_date="20260601" if implementation else None,
        ex_date="20260602" if implementation else None,
        pay_date="20260602" if implementation else None,
        div_listdate=None,
        source_snapshot_id="snap_dividend",
        source_row_sha256="a" * 64,
        input_schema_manifest_id="schema_dividend",
        schema_manifest_id="schema_dividend",
        transform_name="dividend_row_to_pit_events",
        transform_version="1.0.0",
        quality_status="ACCEPTED",
        quality_report_id="quality_dividend",
    )


def _batch() -> CanonicalBatch:
    return CanonicalBatch(
        artifact_id="canonical_dividend_empty",
        source_snapshot_id="snap_dividend_empty",
        schema_manifest_id="schema_dividend",
        transform_name="tushare_raw_to_canonical",
        transform_version="1.1.2",
        quality_status="QUARANTINED",
        collection="canonical_dividend_event",
        records=(),
        field_mappings=("canonical_dividend_event.ts_code<-raw_tushare_dividend.payload.ts_code",),
    )
