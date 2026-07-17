from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data import financial_pipeline
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.financial_store import FinancialWriteResult
from ashare_lab.data.financials import IncomeVersion
from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeMongo:
    def __class_getitem__(cls, _item: type) -> type["FakeMongo"]:
        return cls

    def __init__(self, _uri: str, *, serverSelectionTimeoutMS: int) -> None:  # noqa: N803
        assert serverSelectionTimeoutMS == 8_000

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


class RecordingStore:
    def __init__(self) -> None:
        self.events = 0

    def write_batch(
        self,
        _batch: CanonicalBatch,
        events: tuple[IncomeVersion, ...],
    ) -> FinancialWriteResult:
        self.events = len(events)
        return FinancialWriteResult("batch", len(events), len(events))


def test_income_pipeline_persists_projected_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: one governed income response and isolated persistence boundaries.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_financials_v1.json")
    schema = registry.endpoint("income")
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
    now = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        TushareQuery("income", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(now, now),
    )
    result = SyncResult(StoredSnapshot(raw.snapshot.snapshot_id, 1, inserted=True), raw)
    store = RecordingStore()
    monkeypatch.setattr(financial_pipeline, "MongoClient", FakeMongo)
    monkeypatch.setattr(
        financial_pipeline,
        "MongoFinancialEventStore",
        lambda _client, _database: store,
    )

    # When: the response crosses the PIT pipeline.
    persisted = financial_pipeline.persist_income_results(registry, (result,))

    # Then: one immutable version is persisted and counted.
    assert persisted.event_count == 1
    assert persisted.inserted_count == 1
    assert store.events == 1
