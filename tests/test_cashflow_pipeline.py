from types import TracebackType
from typing import Self

import pytest

from ashare_lab.data import cashflow_cli, cashflow_pipeline
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.cashflow_store import CashflowWriteResult
from ashare_lab.data.cashflows import CashflowVersion
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import TushareQuery
from tests.cashflow_support import raw_result, registry


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


class Store:
    def __init__(self) -> None:
        self.events = 0

    def write_batch(
        self, _batch: CanonicalBatch, events: tuple[CashflowVersion, ...]
    ) -> CashflowWriteResult:
        self.events = len(events)
        return CashflowWriteResult("batch", len(events), len(events))


def test_cashflow_pipeline_persists_projected_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one governed provider result and isolated persistence.
    store = Store()

    def factory(_client: Mongo, _database: str) -> Store:
        return store

    monkeypatch.setattr(cashflow_pipeline, "MongoClient", Mongo)
    monkeypatch.setattr(cashflow_pipeline, "MongoCashflowStore", factory)

    # When: it crosses the cash-flow PIT pipeline.
    result = cashflow_pipeline.persist_cashflow_results(registry(), (raw_result(),))

    # Then: exactly one immutable version is persisted.
    assert result.event_count == 1
    assert result.inserted_count == 1
    assert store.events == 1


def test_cashflow_cli_skips_only_proven_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: one complete and one pending lifecycle code.
    attempted: list[str] = []

    def completed(_registry: SchemaRegistry, _start: str, _end: str) -> frozenset[str]:
        return frozenset({"000001.SZ"})

    def execute(_registry: SchemaRegistry, queries: tuple[TushareQuery, ...]) -> tuple[None, ...]:
        attempted.append(queries[0].params[0].value)
        return ()

    def persist(_registry: SchemaRegistry, _results: tuple[None, ...]) -> None:
        return None

    monkeypatch.setattr(
        cashflow_cli, "load_cashflow_security_codes", lambda: ("000001.SZ", "600000.SH")
    )
    monkeypatch.setattr(cashflow_cli, "load_completed_cashflow_codes", completed)
    monkeypatch.setattr(cashflow_cli, "execute_queries", execute)
    monkeypatch.setattr(cashflow_cli, "persist_cashflow_results", persist)

    # When: one bounded backfill unit resumes.
    cashflow_cli.backfill_cashflow("20200101", "20260716", max_securities=1)

    # Then: only the unproven code reaches the provider boundary.
    assert attempted == ["600000.SH"]
