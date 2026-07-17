from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data import corporate_action_pipeline
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.corporate_action_store import DividendWriteResult
from ashare_lab.data.corporate_actions import DividendEvent
from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

PROJECT_ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeMongoClient:
    """Own a no-op context boundary for pipeline orchestration tests."""

    def __class_getitem__(cls, _item: type) -> type["FakeMongoClient"]:
        return cls

    def __init__(self, _uri: str, *, serverSelectionTimeoutMS: int) -> None:  # noqa: N803
        assert serverSelectionTimeoutMS == 8_000

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


class RecordingStore:
    """Capture projected events without a database dependency."""

    def __init__(self) -> None:
        self.event_types: tuple[str, ...] = ()

    def write_batch(
        self,
        _canonical: CanonicalBatch,
        events: tuple[DividendEvent, ...],
    ) -> DividendWriteResult:
        self.event_types = tuple(event.event_type.value for event in events)
        return DividendWriteResult("dividend_batch", len(events), len(events))


def test_dividend_pipeline_projects_and_persists_both_lifecycle_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one governed dividend response and isolated persistence boundaries.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_corporate_actions_v1.json")
    store = RecordingStore()
    monkeypatch.setattr(corporate_action_pipeline, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(
        corporate_action_pipeline,
        "MongoDividendEventStore",
        lambda _client, _database: store,
    )

    # When: the response crosses the complete PIT pipeline.
    result = corporate_action_pipeline.persist_dividend_results(
        registry,
        (_result(registry, "dividend"),),
    )

    # Then: both stages are persisted and included in observable counts.
    assert result.event_count == 2
    assert result.inserted_count == 2
    assert store.event_types == ("PLAN_ANNOUNCED", "IMPLEMENTATION_ANNOUNCED")


def test_dividend_pipeline_rejects_non_corporate_action_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a daily response presented to the corporate-action pipeline.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    monkeypatch.setattr(corporate_action_pipeline, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(
        corporate_action_pipeline,
        "MongoDividendEventStore",
        lambda _client, _database: RecordingStore(),
    )

    # When / Then: the endpoint boundary fails closed before persistence.
    with pytest.raises(SchemaContractError, match="unsupported corporate-action"):
        corporate_action_pipeline.persist_dividend_results(
            registry,
            (_result(registry, "daily"),),
        )


def _result(registry: SchemaRegistry, endpoint: str) -> SyncResult:
    schema = registry.endpoint(endpoint)
    values: tuple[str | float | None, ...]
    if endpoint == "dividend":
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
    else:
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
    query = TushareQuery(endpoint, (), schema.field_names)
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    batch = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    stored = StoredSnapshot(batch.snapshot.snapshot_id, 1, inserted=True)
    return SyncResult(stored, batch)
