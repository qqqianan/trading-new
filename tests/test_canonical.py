from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pymongo import UpdateOne

from ashare_lab.data.bson_types import BsonValue
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.canonical_store import MongoCanonicalStore
from ashare_lab.data.mongo_documents import canonical_document
from ashare_lab.data.pit import select_available_records
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import QueryParam, TushareClient, TushareQuery

PROJECT_ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeBulkResult:
    """Minimal observable result returned by the canonical fake collection."""

    upserted_count = 1


class FakeCollection:
    """Capture Mongo writes at the adapter boundary."""

    def __init__(self) -> None:
        self.update_calls = 0
        self.last_update: dict[str, BsonValue] = {}

    def bulk_write(
        self,
        operations: list[UpdateOne],
        *,
        ordered: bool,
    ) -> FakeBulkResult:
        assert operations
        assert ordered is False
        return FakeBulkResult()

    def update_one(
        self,
        query: dict[str, BsonValue],
        update: dict[str, BsonValue],
        *,
        upsert: bool,
    ) -> None:
        assert query
        assert update
        assert upsert is True
        self.update_calls += 1
        self.last_update = update


class FakeDatabase:
    """Provide named in-memory collections to the canonical adapter."""

    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class EvidenceCollection:
    """Return preloaded governance evidence for resume detection."""

    def __init__(self, documents: list[dict[str, BsonValue]]) -> None:
        self.documents = documents

    def find(self, _query: dict[str, BsonValue]) -> list[dict[str, BsonValue]]:
        return self.documents

    def find_one(
        self,
        query: dict[str, BsonValue],
        _projection: dict[str, BsonValue] | None = None,
    ) -> dict[str, BsonValue] | None:
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ),
            None,
        )


class EvidenceDatabase:
    """Expose governance collections containing accepted and partial dates."""

    def __init__(self, schema_manifest_id: str) -> None:
        endpoints = ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d")
        complete = [_snapshot(endpoint, "20260601", schema_manifest_id) for endpoint in endpoints]
        partial = [
            _snapshot(endpoint, "20260602", schema_manifest_id) for endpoint in endpoints[:-1]
        ]
        snapshots = complete + partial
        lineage = [
            {
                "upstream_artifact_id": document["snapshot_id"],
                "output_schema_id": schema_manifest_id,
                "downstream_artifact_id": f"canonical_{document['snapshot_id']}",
            }
            for document in snapshots
        ]
        quality = [
            {"artifact_id": edge["downstream_artifact_id"], "passed": True} for edge in lineage
        ]
        self.collections = {
            "meta_source_snapshots": EvidenceCollection(snapshots),
            "meta_lineage_edges": EvidenceCollection(lineage),
            "meta_quality_reports": EvidenceCollection(quality),
        }

    def __getitem__(self, name: str) -> EvidenceCollection:
        return self.collections[name]


def test_daily_canonical_record_has_conservative_pit_time_and_full_lineage() -> None:
    # Given: one schema-valid Raw daily response observed years after the market event.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    schema = registry.endpoint("daily")
    query = TushareQuery(
        endpoint="daily",
        params=(QueryParam("trade_date", "20260710"),),
        fields=schema.field_names,
    )
    values = (
        "000001.SZ",
        "20260710",
        10.1,
        10.3,
        10.0,
        10.2,
        10.0,
        0.2,
        2.0,
        1234.0,
        5678.0,
    )
    observed = datetime(2026, 7, 14, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When: Raw is transformed through the registered canonical policy.
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)

    # Then: PIT availability is deterministic and every business field has lineage.
    record = canonical.records[0]
    assert record.event_time == datetime(2026, 7, 10, 15, 0, tzinfo=SHANGHAI)
    assert record.available_at == datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)
    assert record.quality_status == "ACCEPTED"
    assert len(canonical.field_mappings) == len(schema.fields)
    assert canonical.field_mappings[0].endswith("payload.ts_code")
    document = canonical_document(record)
    assert document["record_id"] == record.record_id
    assert document["open"] == 10.1

    store = MongoCanonicalStore.__new__(MongoCanonicalStore)
    database = FakeDatabase()
    store.__dict__["_database"] = database
    stored = store.write(schema, canonical)
    assert stored.inserted_count == 1
    assert stored.quality_status == "ACCEPTED"
    assert database["meta_quality_reports"].update_calls == 1
    assert database["meta_lineage_edges"].update_calls == 1
    before_release = datetime(2026, 7, 10, 15, 59, tzinfo=SHANGHAI)
    after_release = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)
    assert select_available_records(canonical.records, before_release) == ()
    assert select_available_records(canonical.records, after_release) == canonical.records
    with pytest.raises(ValueError, match="timezone-aware"):
        select_available_records(canonical.records, after_release.replace(tzinfo=None))


def test_current_security_master_is_quarantined_from_historical_pit() -> None:
    # Given: a current stock master snapshot containing a future delisting field.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    schema = registry.endpoint("stock_basic")
    query = TushareQuery("stock_basic", (), schema.field_names)
    values = (
        "000001.SZ",
        "000001",
        "平安银行",
        "深圳",
        "银行",
        "平安银行股份有限公司",
        None,
        "payh",
        "主板",
        "SZSE",
        "CNY",
        "L",
        "19910403",
        None,
        "S",
        None,
        None,
    )
    observed = datetime(2026, 7, 14, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When: the current master record is canonicalized.
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)

    # Then: it remains unavailable to historical training until event splitting exists.
    assert canonical.records[0].quality_status == "QUARANTINED"
    assert canonical.records[0].available_at == observed
    assert select_available_records(canonical.records, observed) == ()


def test_dividend_snapshot_is_quarantined_until_lifecycle_fields_are_split() -> None:
    # Given: one historical dividend row containing both plan and later implementation dates.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_corporate_actions_v1.json")
    schema = registry.endpoint("dividend")
    values = (
        "000001.SZ",
        "20251231",
        "20260320",
        "实施",
        0.0,
        0.0,
        0.0,
        0.5,
        0.45,
        "20260601",
        "20260602",
        "20260602",
        None,
        "20260525",
        "20251231",
        100000.0,
    )
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    query = TushareQuery("dividend", (), schema.field_names)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When: the mixed-lifecycle row reaches canonical storage.
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)

    # Then: direct feature access remains closed until PIT event projection.
    assert canonical.quality_status == "QUARANTINED"
    assert canonical.records[0].quality_status == "QUARANTINED"


def test_income_uses_actual_announcement_clock_and_remains_quarantined() -> None:
    # Given: one income version with nominal and later actual announcement dates.
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

    # When: the mixed current-version row crosses canonical conversion.
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)

    # Then: actual publication controls availability and direct feature access stays closed.
    assert canonical.records[0].available_at == datetime(2026, 3, 22, 18, 0, tzinfo=SHANGHAI)
    assert canonical.quality_status == "QUARANTINED"


def test_completed_market_dates_require_all_five_governance_evidence_chains() -> None:
    # Given: one complete date and one date missing even an empty suspension artifact.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    store = MongoCanonicalStore.__new__(MongoCanonicalStore)
    store.__dict__["_database"] = EvidenceDatabase(registry.manifest_id)

    # When: the resumable cursor is derived from persisted governance evidence.
    completed = store.completed_market_dates(registry.manifest_id, "20260601", "20260630")

    # Then: only the date with all five accepted Raw-to-canonical chains is skipped.
    assert completed == frozenset({"20260601"})


def test_empty_canonical_batch_lineage_retains_current_schema_identity() -> None:
    # Given: a schema-valid suspension response with no rows for the trading date.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    schema = registry.endpoint("suspend_d")
    query = TushareQuery(
        endpoint="suspend_d",
        params=(QueryParam("trade_date", "20260601"),),
        fields=schema.field_names,
    )
    observed = datetime(2026, 6, 1, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, ()),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    database = FakeDatabase()
    store = MongoCanonicalStore.__new__(MongoCanonicalStore)
    store.__dict__["_database"] = database

    # When: the empty batch writes its quality and lineage evidence.
    store.write(schema, canonicalize_batch(raw, schema, registry.manifest_id))

    # Then: the lineage still pins both input and output to the current schema.
    update = database["meta_lineage_edges"].last_update["$setOnInsert"]
    assert isinstance(update, dict)
    assert update["input_schema_ids"] == [registry.manifest_id]
    assert update["output_schema_id"] == registry.manifest_id


def test_empty_current_security_master_batch_remains_quarantined() -> None:
    # Given: a current paused-security request returning no rows.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    schema = registry.endpoint("stock_basic")
    query = TushareQuery(
        endpoint="stock_basic",
        params=(QueryParam("list_status", "P"),),
        fields=schema.field_names,
    )
    observed = datetime(2026, 7, 15, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, ()),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    database = FakeDatabase()
    store = MongoCanonicalStore.__new__(MongoCanonicalStore)
    store.__dict__["_database"] = database

    # When: the empty current-master batch reaches canonical quality storage.
    result = store.write(schema, canonicalize_batch(raw, schema, registry.manifest_id))

    # Then: absence of rows cannot turn a quarantined source into accepted PIT evidence.
    assert result.quality_status == "QUARANTINED"


def test_name_history_uses_effective_date_and_conservative_announcement_time() -> None:
    # Given: an ST name effective after its earlier public announcement.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    schema = registry.endpoint("namechange")
    query = TushareQuery(endpoint="namechange", params=(), fields=schema.field_names)
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(
            schema.field_names,
            (("000001.SZ", "ST平安", "20200501", "20200630", "20200430", "ST"),),
        ),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When: the historical name row is canonicalized.
    record = canonicalize_batch(raw, schema, registry.manifest_id).records[0]

    # Then: economic effectiveness and public availability remain distinct.
    assert record.event_time == datetime(2020, 5, 1, 0, 0, tzinfo=SHANGHAI)
    assert record.available_at == datetime(2020, 4, 30, 18, 0, tzinfo=SHANGHAI)


def test_name_history_without_announcement_is_only_available_when_observed() -> None:
    # Given: a historical name row whose provider omits announcement date.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    schema = registry.endpoint("namechange")
    query = TushareQuery(endpoint="namechange", params=(), fields=schema.field_names)
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(
            schema.field_names,
            (("000001.SZ", "平安银行", "19910403", None, None, None),),
        ),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When: the row crosses the canonical PIT policy.
    record = canonicalize_batch(raw, schema, registry.manifest_id).records[0]

    # Then: missing publication evidence cannot be backdated.
    assert record.available_at == observed


def test_same_day_name_announcement_cannot_be_available_after_observation() -> None:
    # Given: a same-day announcement already present in a morning provider response.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    schema = registry.endpoint("namechange")
    query = TushareQuery(endpoint="namechange", params=(), fields=schema.field_names)
    observed = datetime(2026, 7, 16, 9, 15, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(
            schema.field_names,
            (("920117.BJ", "N国亮", "20260716", None, "20260716", "上市"),),
        ),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When: the already-observed row crosses the availability policy.
    record = canonicalize_batch(raw, schema, registry.manifest_id).records[0]

    # Then: a conventional 18:00 timestamp cannot make known data artificially future-dated.
    assert record.available_at == observed


def _snapshot(
    endpoint: str,
    trade_date: str,
    schema_manifest_id: str,
) -> dict[str, BsonValue]:
    snapshot_id = f"snap_{endpoint}_{trade_date}"
    return {
        "snapshot_id": snapshot_id,
        "endpoint": endpoint,
        "request_params_canonical": f'{{"trade_date":"{trade_date}"}}',
        "schema_manifest_id": schema_manifest_id,
        "status": "ACCEPTED",
    }
