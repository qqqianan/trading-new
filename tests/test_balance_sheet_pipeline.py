from types import TracebackType
from typing import Self

import pytest

from ashare_lab.data import balance_sheet_pipeline
from ashare_lab.data.balance_sheet_store import BalanceSheetWriteResult
from ashare_lab.data.balance_sheets import BalanceSheetVersion
from ashare_lab.data.canonical import CanonicalBatch
from tests.balance_sheet_support import registry, sync_result


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
        self,
        _batch: CanonicalBatch,
        events: tuple[BalanceSheetVersion, ...],
    ) -> BalanceSheetWriteResult:
        self.events = len(events)
        return BalanceSheetWriteResult("batch", len(events), len(events))


def test_balance_sheet_pipeline_persists_projected_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one governed response and isolated persistence boundaries.
    store = Store()

    def store_factory(_client: Mongo, _database: str) -> Store:
        return store

    monkeypatch.setattr(balance_sheet_pipeline, "MongoClient", Mongo)
    monkeypatch.setattr(
        balance_sheet_pipeline,
        "MongoBalanceSheetStore",
        store_factory,
    )

    # When: the batch crosses the only PIT orchestration path.
    result = balance_sheet_pipeline.persist_balance_sheet_results(registry(), (sync_result(),))

    # Then: one accepted immutable version is persisted and counted.
    assert result.event_count == 1
    assert result.inserted_count == 1
    assert store.events == 1
