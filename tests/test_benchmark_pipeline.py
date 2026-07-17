from types import TracebackType
from typing import Self

import pytest

from ashare_lab.data import benchmark_cli, benchmark_pipeline
from ashare_lab.data.benchmark_documents import index_weight_document, index_weight_lineage
from ashare_lab.data.benchmark_store import BenchmarkWriteResult, MongoBenchmarkWeightStore
from ashare_lab.data.benchmark_weights import IndexWeightEvent, build_index_weight_event
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import TushareQuery
from tests.benchmark_support import benchmark_registry, weight_canonical, weight_sync_result
from tests.test_balance_sheet_store import Database


class Mongo:
    def __class_getitem__(cls, _item: type) -> type["Mongo"]:
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
        self, _batch: CanonicalBatch, events: tuple[IndexWeightEvent, ...]
    ) -> BenchmarkWriteResult:
        self.events = len(events)
        return BenchmarkWriteResult("batch", len(events), len(events))


def test_benchmark_store_writes_events_lineage_and_empty_month_evidence() -> None:
    # Given: two validated weight events and an isolated Mongo fake.
    canonical = weight_canonical()
    events = tuple(build_index_weight_event(record) for record in canonical.records)
    database = Database()
    store = MongoBenchmarkWeightStore.__new__(MongoBenchmarkWeightStore)
    store.__dict__["_database"] = database

    # When: populated and empty monthly batches are persisted.
    result = store.write_batch(canonical, events)
    empty = CanonicalBatch(
        "empty",
        "snap",
        "schema",
        "transform",
        "1",
        "QUARANTINED",
        "canonical_index_membership",
        (),
        (),
    )
    empty_result = store.write_batch(empty, ())

    # Then: values, field lineage, and both monthly proofs are explicit.
    assert index_weight_document(events[0])["weight"] == 60.0
    mappings = index_weight_lineage(events[0], "a" * 40)["field_mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) == 5
    assert result.inserted_count == 1
    assert empty_result.event_count == 0
    assert database["meta_quality_reports"].update_calls == 2


def test_benchmark_pipeline_and_cli_use_governed_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one governed provider response and recording boundaries.
    store = RecordingStore()
    executed: list[str] = []

    def factory(_client: Mongo, _database: str) -> RecordingStore:
        return store

    def execute(_registry: SchemaRegistry, queries: tuple[TushareQuery, ...]) -> tuple[None, ...]:
        executed.append(queries[0].endpoint)
        return ()

    def discard(_registry: SchemaRegistry, _results: tuple[None, ...]) -> None:
        return None

    monkeypatch.setattr(benchmark_pipeline, "MongoClient", Mongo)
    monkeypatch.setattr(benchmark_pipeline, "MongoBenchmarkWeightStore", factory)
    monkeypatch.setattr(benchmark_cli, "execute_queries", execute)
    monkeypatch.setattr(benchmark_cli, "persist_benchmark_weight_results", discard)

    # When: PIT projection and each CLI command execute.
    persisted = benchmark_pipeline.persist_benchmark_weight_results(
        benchmark_registry(), (weight_sync_result(),)
    )
    benchmark_cli.sync_benchmark_master()
    benchmark_cli.backfill_benchmark_daily("20200101", "20260716")
    benchmark_cli.backfill_benchmark_weights("20200101", "20200131", 1)

    # Then: events persist and all provider calls use registered endpoint paths.
    assert persisted.event_count == 2
    assert store.events == 2
    assert executed == ["index_basic", "index_daily", "index_weight"]
