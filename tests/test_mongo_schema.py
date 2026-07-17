from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.mongo_documents import raw_document, snapshot_document, validator_document
from ashare_lab.data.mongo_schema import MongoSchemaBuilder
from ashare_lab.data.mongo_store import MongoRawStore, RawPersistenceError
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import RawRow, SourceSnapshot

PROJECT_ROOT = Path(__file__).parents[1]


class IndexRecordingCollection:
    """Capture index names created by the Mongo adapter."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def create_index(self, _keys: str | list[tuple[str, int]], **options: str | bool) -> None:
        name = options.get("name")
        assert isinstance(name, str)
        self.names.append(name)


class IndexRecordingDatabase:
    """Expose one collection for index initialization tests."""

    def __init__(self) -> None:
        self.collection = IndexRecordingCollection()

    def __getitem__(self, _name: str) -> IndexRecordingCollection:
        return self.collection


def test_raw_validator_closes_envelope_and_provider_payload() -> None:
    # Given: the committed daily endpoint schema.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")

    # When: a MongoDB validator is generated for its Raw collection.
    validator = MongoSchemaBuilder(registry).raw_validator(registry.endpoint("daily"))

    # Then: both envelope and payload reject undocumented fields.
    root = validator.root
    payload = root.property("payload")
    assert root.additional_properties is False
    assert payload.additional_properties is False
    assert "snapshot_id" in root.required
    assert payload.required == tuple(
        field[0] for field in registry.endpoint("daily").fields if not field[2]
    )


def test_daily_validator_allows_missing_pre_close_on_first_trading_day() -> None:
    # Given: the committed daily contract used for historical first-day records.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")

    # When: the Raw payload validator is generated.
    payload = (
        MongoSchemaBuilder(registry)
        .raw_validator(registry.endpoint("daily"))
        .root.property("payload")
    )

    # Then: pre-close remains documented but permits the provider's legitimate null value.
    assert "pre_close" not in payload.required
    assert "null" in payload.property("pre_close").bson_types


def test_collection_plan_contains_only_new_database_contracts() -> None:
    # Given: the P0 schema registry.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")

    # When: the initializer builds its collection plan.
    plan = MongoSchemaBuilder(registry).collection_plan()

    # Then: five governance, seven Raw, and seven canonical collections are isolated.
    assert len(plan) == 19
    assert "meta_source_snapshots" in plan
    assert "raw_tushare_daily" in plan
    assert "canonical_daily_bar" in plan


def test_universe_schema_manages_pit_events_without_changing_daily_manifest() -> None:
    # Given: a separate universe bundle and the established daily bundle.
    daily = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    universe = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")

    # When: the universe collection plan is generated.
    plan = MongoSchemaBuilder(universe).collection_plan()

    # Then: PIT events are managed independently from the immutable daily schema identity.
    assert "pit_security_events" in plan
    assert universe.endpoint_names == ("namechange", "stock_basic")
    assert universe.manifest_id != daily.manifest_id


def test_mongo_documents_preserve_schema_and_raw_lineage() -> None:
    # Given: a typed validator, snapshot, and provider row.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    validator = MongoSchemaBuilder(registry).raw_validator(registry.endpoint("adj_factor"))
    now = datetime(2026, 7, 14, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    snapshot = SourceSnapshot(
        snapshot_id="snap_abc",
        source="tushare",
        endpoint="adj_factor",
        request_params_canonical='{"trade_date":"20260710"}',
        requested_at=now,
        completed_at=now,
        provider_version=None,
        row_count=1,
        payload_sha256="a" * 64,
        schema_manifest_id=registry.manifest_id,
        status="RECEIVED",
    )
    row = RawRow(
        snapshot_id="snap_abc",
        row_ordinal=0,
        ingested_at=now,
        row_sha256="b" * 64,
        payload=(("ts_code", "000001.SZ"), ("trade_date", "20260710")),
    )

    # When: storage command documents are serialized.
    validator_doc = validator_document(validator)
    snapshot_doc = snapshot_document(snapshot)
    row_doc = raw_document(row)

    # Then: closed schema rules and source identities remain intact.
    root_doc = validator_doc["$jsonSchema"]
    payload_doc = row_doc["payload"]
    assert isinstance(root_doc, dict)
    assert isinstance(payload_doc, dict)
    assert root_doc["additionalProperties"] is False
    assert snapshot_doc["schema_manifest_id"] == registry.manifest_id
    assert payload_doc == {"ts_code": "000001.SZ", "trade_date": "20260710"}


def test_store_rejects_wrong_database_and_errors_do_not_dump_payloads() -> None:
    # Given: a lazy Mongo client and a non-secret snapshot identity.
    client = MongoClient[BsonDocument](connect=False)
    error = RawPersistenceError("snap_abc")

    # When / Then: legacy database selection is rejected before any connection.
    with pytest.raises(ValueError, match="restricted to ashare_quant"):
        MongoRawStore(client, "wrong_database")
    assert str(error) == "Raw snapshot failed MongoDB validation: snap_abc"
    client.close()


def test_mongo_rule_rejects_undocumented_property_lookup() -> None:
    # Given: a closed Raw validator.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    root = MongoSchemaBuilder(registry).raw_validator(registry.endpoint("daily")).root

    # When / Then: generated code cannot silently address an undocumented field.
    with pytest.raises(KeyError, match="not documented"):
        root.property("future_field")


def test_pit_security_events_receive_identity_and_point_in_time_indexes() -> None:
    # Given: a Mongo adapter with an index-recording collection.
    store = MongoRawStore.__new__(MongoRawStore)
    database = IndexRecordingDatabase()
    store.__dict__["_database"] = database

    # When: indexes are initialized for the PIT event collection.
    store._create_indexes("pit_security_events")  # noqa: SLF001

    # Then: identity and decision-time query paths are both indexed.
    assert database.collection.names == ["event_id_unique", "pit_state_lookup"]


def test_governance_evidence_receives_resume_lookup_indexes() -> None:
    # Given: a Mongo adapter with index-recording governance collections.
    store = MongoRawStore.__new__(MongoRawStore)
    database = IndexRecordingDatabase()
    store.__dict__["_database"] = database

    # When: lineage and quality indexes are initialized.
    store._create_indexes("meta_lineage_edges")  # noqa: SLF001
    store._create_indexes("meta_quality_reports")  # noqa: SLF001

    # Then: resume checks can prove both graph edges and passed artifact quality efficiently.
    assert database.collection.names == [
        "lineage_upstream_output",
        "lineage_downstream_output",
        "quality_artifact_passed",
    ]
