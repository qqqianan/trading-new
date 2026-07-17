from pathlib import Path
from types import TracebackType
from typing import Self

import httpx2
import pytest

from ashare_lab.data import execution
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.canonical_store import CanonicalWriteResult
from ashare_lab.data.mongo_store import MongoRawStore, StoredSnapshot
from ashare_lab.data.schema_registry import EndpointSchema, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotBatch
from ashare_lab.data.tushare_client import TushareClient, TushareQuery, TushareTable

ROOT = Path(__file__).parents[1]


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


class RawStore(MongoRawStore):
    def __init__(self) -> None:
        self.writes = 0

    def initialize(self, _registry: SchemaRegistry) -> tuple[str, ...]:
        return ()

    def write_batch(self, _schema: EndpointSchema, batch: SnapshotBatch) -> StoredSnapshot:
        self.writes += 1
        return StoredSnapshot(batch.snapshot.snapshot_id, len(batch.rows), inserted=True)


class StaticClient(TushareClient):
    def __init__(self, fields: tuple[str, ...]) -> None:
        self.fields = fields

    def fetch(self, query: TushareQuery) -> TushareTable:
        assert query.fields == self.fields
        return self.table_for_test(self.fields, (("000001.SZ", "20260710", 1.0),))


class CanonicalStore:
    def __init__(self) -> None:
        self.writes = 0

    def write(
        self,
        _schema: EndpointSchema,
        batch: CanonicalBatch,
    ) -> CanonicalWriteResult:
        self.writes += 1
        return CanonicalWriteResult(batch.artifact_id, len(batch.records), 1, "ACCEPTED")


def test_execute_queries_owns_the_complete_governed_call_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: real synchronization logic with isolated provider and Mongo boundaries.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_p0_v1.json")
    fields = ("ts_code", "trade_date", "adj_factor")
    raw_store = RawStore()
    canonical_store = CanonicalStore()
    monkeypatch.setattr(execution, "MongoClient", FakeMongo)
    monkeypatch.setattr(execution, "MongoRawStore", lambda _mongo, _database: raw_store)
    monkeypatch.setattr(
        execution,
        "MongoCanonicalStore",
        lambda _mongo, _database: canonical_store,
    )
    monkeypatch.setattr(execution, "create_provider_client", httpx2.Client)
    monkeypatch.setattr(execution, "TushareClient", lambda _token, _http: StaticClient(fields))

    # When: one registered query is executed.
    results = execution.execute_queries(
        registry,
        (TushareQuery("adj_factor", (), fields),),
    )

    # Then: Raw and canonical stores both observe the validated batch.
    assert len(results) == 1
    assert raw_store.writes == 1
    assert canonical_store.writes == 1
