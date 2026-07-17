from types import TracebackType
from typing import Self

import pytest

from ashare_lab.data import industry_cli, industry_pipeline
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.industry_documents import (
    industry_membership_document,
    industry_membership_lineage,
)
from ashare_lab.data.industry_memberships import (
    IndustryMembership,
    build_industry_membership,
)
from ashare_lab.data.industry_store import IndustryWriteResult, MongoIndustryStore
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareQuery
from tests.industry_support import (
    industry_registry,
    member_canonical,
    member_result,
    taxonomy_result,
)
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
        self,
        _batch: CanonicalBatch,
        events: tuple[IndustryMembership, ...],
    ) -> IndustryWriteResult:
        self.events = len(events)
        return IndustryWriteResult("batch", len(events), len(events))


def test_industry_store_writes_intervals_lineage_and_batch_evidence() -> None:
    # Given: one accepted observed-at interval and an isolated Mongo fake.
    canonical = member_canonical()
    event = build_industry_membership(canonical.records[0])
    database = Database()
    store = MongoIndustryStore.__new__(MongoIndustryStore)
    store.__dict__["_database"] = database

    # When: the interval crosses the Mongo boundary.
    result = store.write_batch(canonical, (event,))
    empty = CanonicalBatch(
        "empty",
        "snap",
        canonical.schema_manifest_id,
        "transform",
        "1",
        "QUARANTINED",
        canonical.collection,
        (),
        (),
    )
    empty_result = store.write_batch(empty, ())

    # Then: closed fields, evidence, and field mappings are persisted.
    assert industry_membership_document(event)["con_code"] == "000592.SZ"
    mappings = industry_membership_lineage(event, "a" * 40)["field_mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) == 8
    assert result.inserted_count == 1
    assert empty_result.event_count == 0
    assert database["meta_quality_reports"].bulk_calls == 1
    assert database["meta_lineage_edges"].bulk_calls == 1
    assert database["meta_quality_reports"].update_calls == 2


def test_industry_pipeline_and_cli_keep_governed_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: governed taxonomy/member responses and recording adapters.
    store = RecordingStore()
    calls: list[str] = []

    def factory(_client: Mongo, _database: str) -> RecordingStore:
        return store

    def execute(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[SyncResult, ...]:
        endpoint = queries[0].endpoint
        calls.append(endpoint)
        return (taxonomy_result(),) if endpoint == "index_classify" else (member_result(),)

    def discard(_registry: SchemaRegistry, _results: tuple[SyncResult, ...]) -> None:
        return None

    monkeypatch.setattr(industry_pipeline, "MongoClient", Mongo)
    monkeypatch.setattr(industry_pipeline, "MongoIndustryStore", factory)
    monkeypatch.setattr(industry_cli, "execute_queries", execute)
    monkeypatch.setattr(industry_cli, "persist_industry_results", discard)

    # When: PIT persistence and one bounded CLI request execute.
    persisted = industry_pipeline.persist_industry_results(
        industry_registry(),
        (member_result(),),
    )
    industry_cli.sync_industries(max_requests=1)

    # Then: one accepted interval persists and every provider call is governed.
    assert persisted.event_count == 1
    assert store.events == 1
    assert calls == ["index_classify", "index_member"]


def test_industry_pipeline_rejects_non_member_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a taxonomy response routed to the membership projector.
    def factory(_client: Mongo, _database: str) -> RecordingStore:
        return RecordingStore()

    monkeypatch.setattr(industry_pipeline, "MongoClient", Mongo)
    monkeypatch.setattr(industry_pipeline, "MongoIndustryStore", factory)

    # When / Then: endpoint confusion fails before any event is invented.
    with pytest.raises(SchemaContractError, match="unsupported industry endpoint"):
        industry_pipeline.persist_industry_results(
            industry_registry(),
            (taxonomy_result(),),
        )
