from datetime import datetime
from types import TracebackType
from typing import Self
from zoneinfo import ZoneInfo

import pytest
from pymongo import UpdateOne

from ashare_lab.data import (
    financial_indicator_cli,
    financial_indicator_pipeline,
    financial_indicator_progress,
)
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import CanonicalBatch, canonicalize_batch
from ashare_lab.data.cashflow_store import cashflow_batch_artifact_id
from ashare_lab.data.financial_indicator_documents import (
    financial_indicator_document,
    financial_indicator_lineage,
)
from ashare_lab.data.financial_indicator_store import (
    IndicatorWriteResult,
    MongoFinancialIndicatorStore,
)
from ashare_lab.data.financial_indicators import (
    FinancialIndicatorVersion,
    build_financial_indicator_version,
)
from ashare_lab.data.queries import financial_indicator_security_queries
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import TushareQuery
from tests.financial_indicator_support import raw_result, registry
from tests.test_cashflow_progress import Mongo as ProgressMongo


class BulkResult:
    upserted_count = 1


class Collection:
    def __init__(self) -> None:
        self.bulk_calls = self.update_calls = 0

    def bulk_write(self, operations: list[UpdateOne], *, ordered: bool) -> BulkResult:
        assert operations
        assert ordered is False
        self.bulk_calls += 1
        return BulkResult()

    def update_one(self, _query: BsonDocument, _update: BsonDocument, *, upsert: bool) -> None:
        assert upsert is True
        self.update_calls += 1


class Database:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}

    def __getitem__(self, name: str) -> Collection:
        return self.collections.setdefault(name, Collection())


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
        self, _batch: CanonicalBatch, events: tuple[FinancialIndicatorVersion, ...]
    ) -> IndicatorWriteResult:
        self.events = len(events)
        return IndicatorWriteResult("batch", len(events), len(events))


def _canonical() -> CanonicalBatch:
    result = raw_result()
    registered = registry()
    return canonicalize_batch(
        result.batch, registered.endpoint("fina_indicator"), registered.manifest_id
    )


def test_indicator_version_uses_announcement_clock_and_closed_lineage() -> None:
    # Given: one governed indicator row observed after its announcement.
    canonical = _canonical()

    # When: it crosses PIT and document boundaries.
    event = build_financial_indicator_version(canonical.records[0])
    document = financial_indicator_document(event)
    lineage = financial_indicator_lineage(event, "a" * 40)
    repeated_lineage = financial_indicator_lineage(event, "b" * 40)

    # Then: announcement controls visibility and all committed fields have lineage.
    assert event.available_at == datetime(2026, 3, 22, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert document["eps"] == 1.0
    assert canonical.quality_status == "QUARANTINED"
    mappings = lineage["field_mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) == len(registry().endpoint("fina_indicator").fields) + 1
    assert lineage["code_commit"] == "a" * 40
    assert lineage["lineage_edge_id"] != repeated_lineage["lineage_edge_id"]


def test_indicator_store_writes_event_and_empty_batch_evidence() -> None:
    # Given: one version and an isolated Mongo fake.
    canonical = _canonical()
    event = build_financial_indicator_version(canonical.records[0])
    database = Database()
    store = MongoFinancialIndicatorStore.__new__(MongoFinancialIndicatorStore)
    store.__dict__["_database"] = database

    # When: populated and empty batches are persisted.
    result = store.write_batch(canonical, (event,))
    empty = CanonicalBatch(
        "empty",
        "snap",
        "schema",
        "transform",
        "1",
        "QUARANTINED",
        "canonical_financial_indicator",
        (),
        (),
    )
    empty_result = store.write_batch(empty, ())

    # Then: no empty event is invented and both batch proofs exist.
    assert result.inserted_count == 1
    assert empty_result.event_count == 0
    assert database["pit_financial_indicators"].bulk_calls == 1
    assert database["meta_quality_reports"].update_calls == 2


def test_indicator_pipeline_and_cli_use_only_governed_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: isolated persistence and one pending lifecycle code.
    store = RecordingStore()

    def factory(_client: Mongo, _database: str) -> RecordingStore:
        return store

    def execute(_registry: SchemaRegistry, queries: tuple[TushareQuery, ...]) -> tuple[None, ...]:
        assert queries[0].endpoint == "fina_indicator"
        return ()

    def completed(_registry: SchemaRegistry, _start: str, _end: str) -> frozenset[str]:
        return frozenset()

    def discard(_registry: SchemaRegistry, _results: tuple[None, ...]) -> None:
        return None

    monkeypatch.setattr(financial_indicator_pipeline, "MongoClient", Mongo)
    monkeypatch.setattr(financial_indicator_pipeline, "MongoFinancialIndicatorStore", factory)

    # When: provider result and CLI request cross their real orchestrators.
    persisted = financial_indicator_pipeline.persist_financial_indicator_results(
        registry(), (raw_result(),)
    )
    monkeypatch.setattr(
        financial_indicator_cli, "load_indicator_security_codes", lambda: ("000001.SZ",)
    )
    monkeypatch.setattr(financial_indicator_cli, "load_completed_indicator_codes", completed)
    monkeypatch.setattr(financial_indicator_cli, "execute_queries", execute)
    monkeypatch.setattr(financial_indicator_cli, "persist_financial_indicator_results", discard)
    financial_indicator_cli.backfill_financial_indicators("20200101", "20260716", 1)

    # Then: PIT persistence received one version.
    assert persisted.event_count == 1
    assert store.events == 1


def test_indicator_queries_pin_code_range_and_fields() -> None:
    # Given / When: a bounded lifecycle request is built.
    queries = financial_indicator_security_queries(
        registry(), ("000001.SZ",), "20200101", "20260716"
    )

    # Then: endpoint, code, dates, and projection are explicit.
    assert queries[0].endpoint == "fina_indicator"
    assert tuple(param.value for param in queries[0].params) == (
        "000001.SZ",
        "20200101",
        "20260716",
    )


def test_indicator_progress_requires_complete_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: one accepted range with canonical, PIT lineage, and passed quality evidence.
    monkeypatch.setattr(financial_indicator_progress, "MongoClient", ProgressMongo)
    monkeypatch.setattr(
        financial_indicator_progress, "indicator_batch_artifact_id", cashflow_batch_artifact_id
    )
    schema = SchemaRegistry.__new__(SchemaRegistry)
    schema.__dict__["_manifest_id"] = "schema"

    # When: completion is reconstructed from governance evidence.
    completed = financial_indicator_progress.load_completed_indicator_codes(
        schema, "20200101", "20260716"
    )

    # Then: the evidenced code alone is resumable.
    assert completed == frozenset({"000001.SZ"})
