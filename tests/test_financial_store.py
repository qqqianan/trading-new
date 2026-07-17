from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pymongo import UpdateOne

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import CanonicalBatch, canonicalize_batch
from ashare_lab.data.financial_documents import income_version_document, income_version_lineage
from ashare_lab.data.financial_store import MongoFinancialEventStore
from ashare_lab.data.financials import build_income_version
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

PROJECT_ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeBulkResult:
    upserted_count = 1


class FakeCollection:
    def __init__(self) -> None:
        self.bulk_calls = 0
        self.update_calls = 0

    def bulk_write(self, operations: list[UpdateOne], *, ordered: bool) -> FakeBulkResult:
        assert operations
        assert ordered is False
        self.bulk_calls += 1
        return FakeBulkResult()

    def update_one(
        self,
        _query: BsonDocument,
        _update: BsonDocument,
        *,
        upsert: bool,
    ) -> None:
        assert upsert is True
        self.update_calls += 1


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def test_income_version_document_and_lineage_cover_every_financial_field() -> None:
    # Given: one schema-valid income version projected from governed canonical data.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_financials_v1.json")
    schema = registry.endpoint("income_vip")
    values = (
        "000001.SZ",
        "20260320",
        "20260322",
        "20251231",
        "1",
        "1",
        "4",
        1.0,
        1.0,
        100.0,
        90.0,
        20.0,
        18.0,
        3.0,
        15.0,
        14.0,
        22.0,
        25.0,
        5.0,
        "1",
    )
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        TushareQuery("income_vip", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)
    event = build_income_version(canonical.records[0], "income_vip")

    # When: event and lineage documents cross the Mongo boundary.
    document = income_version_document(event)
    lineage = income_version_lineage(event, "a" * 40)

    # Then: report values and actual-publication mapping are explicit.
    assert document["n_income_attr_p"] == 14.0
    mappings = lineage["field_mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) == len(schema.fields) + 1
    assert (
        "pit_income_statements.effective_at<-raw_tushare_income_vip.payload.f_ann_date|ann_date"
    ) in mappings

    store = MongoFinancialEventStore.__new__(MongoFinancialEventStore)
    database = FakeDatabase()
    store.__dict__["_database"] = database
    result = store.write_batch(canonical, (event,))
    assert result.inserted_count == 1
    assert database["pit_income_statements"].bulk_calls == 1
    assert database["meta_quality_reports"].bulk_calls == 1
    assert database["meta_lineage_edges"].bulk_calls == 1


def test_empty_income_period_still_writes_batch_evidence() -> None:
    # Given: an empty quarantined canonical period.
    batch = CanonicalBatch(
        artifact_id="canonical_income_empty",
        source_snapshot_id="snap_income_empty",
        schema_manifest_id="schema_income",
        transform_name="tushare_raw_to_canonical",
        transform_version="1.1.2",
        quality_status="QUARANTINED",
        collection="canonical_income_statement",
        records=(),
        field_mappings=(),
    )
    store = MongoFinancialEventStore.__new__(MongoFinancialEventStore)
    database = FakeDatabase()
    store.__dict__["_database"] = database

    # When: empty PIT projection completes.
    result = store.write_batch(batch, ())

    # Then: no event is invented but completion quality and lineage are written.
    assert result.event_count == 0
    assert database["meta_quality_reports"].update_calls == 1
    assert database["meta_lineage_edges"].update_calls == 1
