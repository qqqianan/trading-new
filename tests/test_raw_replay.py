from datetime import UTC, datetime

import pytest

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.mongo_raw_replay import MongoRawReplayReader
from ashare_lab.data.raw_replay import RawReplayError, build_stored_snapshot_batch
from ashare_lab.data.schema_registry import (
    EndpointSchema,
    FieldType,
    SchemaBundle,
    SchemaRegistry,
)


class _Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self._documents = documents

    def find(
        self,
        _query: BsonDocument,
        _projection: BsonDocument | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> tuple[BsonDocument, ...]:
        return self._documents if sort is None else tuple(self._documents)

    def find_one(self, _query: BsonDocument) -> BsonDocument | None:
        return self._documents[0] if self._documents else None


class _Database:
    def __init__(self, name: str, documents: dict[str, tuple[BsonDocument, ...]]) -> None:
        self.name = name
        self._documents = documents

    def __getitem__(self, collection: str) -> _Collection:
        return _Collection(self._documents[collection])


def replay_schema() -> EndpointSchema:
    return EndpointSchema(
        raw_collection="raw_tushare_daily",
        canonical_collection="canonical_daily_bar",
        natural_key=("ts_code", "trade_date"),
        event_time_field="trade_date",
        available_at_policy="trade_date_close_plus_provider_delay",
        fields=(
            ("ts_code", FieldType.STRING, False, "code", "identity", "filter"),
            ("trade_date", FieldType.DATE_YYYYMMDD, False, "date", "event_time", "filter"),
            ("close", FieldType.FLOAT, False, "CNY", "market_value", "execution"),
        ),
    )


def replay_registry() -> SchemaRegistry:
    bundle = SchemaBundle(
        schema_version="1.0.0",
        database="ashare_quant",
        source="tushare",
        field_tuple=("name", "type", "nullable", "unit", "time_role", "allowed_use"),
        raw_envelope=(),
        canonical_envelope=(),
        governance_collections={},
        endpoints={"daily": replay_schema()},
    )
    return SchemaRegistry(bundle, "schema_abc")


def replay_snapshot(*, row_count: int = 1) -> BsonDocument:
    return {
        "_id": "snap_001",
        "snapshot_id": "snap_001",
        "source": "tushare",
        "endpoint": "daily",
        "request_params_canonical": '{"trade_date":"20260716"}',
        "requested_at": datetime(2026, 7, 16, 7, 30, tzinfo=UTC),
        "completed_at": datetime(2026, 7, 16, 7, 31, tzinfo=UTC),
        "provider_version": None,
        "row_count": row_count,
        "payload_sha256": "a" * 64,
        "schema_manifest_id": "schema_abc",
        "status": "ACCEPTED",
    }


def replay_row(*, ordinal: int = 0) -> BsonDocument:
    return {
        "_id": f"snap_001:{ordinal}",
        "snapshot_id": "snap_001",
        "row_ordinal": ordinal,
        "ingested_at": datetime(2026, 7, 16, 7, 31, tzinfo=UTC),
        "row_sha256": "b" * 64,
        "payload": {
            "ts_code": "000001.SZ",
            "trade_date": "20260716",
            "close": 10.5,
        },
    }


def test_raw_replay_restores_a_schema_ordered_snapshot_batch() -> None:
    # Given: an accepted stored snapshot and its immutable Raw row.
    # When: the replay boundary reconstructs canonical input.
    batch = build_stored_snapshot_batch(replay_snapshot(), (replay_row(),), replay_schema())

    # Then: identity, ordering, values, and accepted status are preserved.
    assert batch.snapshot.snapshot_id == "snap_001"
    assert batch.snapshot.status == "ACCEPTED"
    assert batch.rows[0].row_ordinal == 0
    assert batch.rows[0].payload == (
        ("ts_code", "000001.SZ"),
        ("trade_date", "20260716"),
        ("close", 10.5),
    )


def test_raw_replay_rejects_missing_rows() -> None:
    # Given: a snapshot claiming two rows while only one is present.
    # When / Then: incomplete Raw cannot be re-materialized.
    with pytest.raises(RawReplayError, match="row_count_mismatch"):
        build_stored_snapshot_batch(
            replay_snapshot(row_count=2),
            (replay_row(),),
            replay_schema(),
        )


def test_raw_replay_rejects_noncontiguous_ordinals() -> None:
    # Given: a stored row whose ordinal does not begin at zero.
    # When / Then: unstable ordering is rejected before canonical conversion.
    with pytest.raises(RawReplayError, match="row_order_mismatch"):
        build_stored_snapshot_batch(
            replay_snapshot(),
            (replay_row(ordinal=1),),
            replay_schema(),
        )


def test_raw_replay_rejects_missing_committed_fields() -> None:
    # Given: a Raw payload that no longer satisfies its committed schema.
    row = replay_row()
    row["payload"] = {"ts_code": "000001.SZ", "trade_date": "20260716"}

    # When / Then: replay cannot invent the missing close value.
    with pytest.raises(RawReplayError, match="field_contract_mismatch"):
        build_stored_snapshot_batch(replay_snapshot(), (row,), replay_schema())


def test_mongo_raw_reader_loads_only_accepted_current_schema_batches() -> None:
    # Given: an in-memory Mongo boundary containing one complete Raw response.
    database = _Database(
        "ashare_quant",
        {
            "meta_source_snapshots": (replay_snapshot(),),
            "raw_tushare_daily": (replay_row(),),
        },
    )
    reader = MongoRawReplayReader(database)

    # When: current-schema identities and one batch are loaded.
    snapshot_ids = reader.accepted_snapshot_ids(replay_registry(), ("daily",))
    batch = reader.load_batch(replay_registry(), snapshot_ids[0])

    # Then: the strict replay boundary returns the exact accepted response.
    assert snapshot_ids == ("snap_001",)
    assert batch.rows[0].payload[-1] == ("close", 10.5)


def test_mongo_raw_reader_rejects_an_unowned_database() -> None:
    # Given: a database outside the governed isolation boundary.
    database = _Database("legacy", {})

    # When / Then: no Raw collection is opened.
    with pytest.raises(RawReplayError, match="database_isolation"):
        MongoRawReplayReader(database)
