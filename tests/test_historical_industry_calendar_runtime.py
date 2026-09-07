from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from ashare_lab.data import historical_industry_calendar_runtime
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.schema_registry import SchemaRegistry
from tests.test_historical_industry_calendar import _rows

ROOT = Path(__file__).parents[1]


class Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.documents = documents
        self.queries: list[BsonDocument] = []

    def find(self, query: BsonDocument, _projection: BsonDocument) -> tuple[BsonDocument, ...]:
        self.queries.append(query)
        return self.documents


class Database:
    def __init__(self, collection: Collection) -> None:
        self.collection = collection

    def __getitem__(self, _name: str) -> Collection:
        return self.collection


class Mongo:
    database: Database

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

    def __getitem__(self, _name: str) -> Database:
        return self.database


def test_calendar_runtime_reads_only_current_schema_accepted_sse_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: canonical rows under the currently committed market schema.
    schema_id = SchemaRegistry.load(ROOT / "schemas" / "tushare_p0_v1.json").manifest_id
    documents = tuple(
        row.model_copy(update={"schema_manifest_id": schema_id}).model_dump(mode="python")
        for row in _rows()
    )
    collection = Collection(documents)
    Mongo.database = Database(collection)
    monkeypatch.setattr(historical_industry_calendar_runtime, "MongoClient", Mongo)

    # When: the read-only availability calendar is loaded.
    calendar = historical_industry_calendar_runtime.load_historical_industry_calendar(
        ROOT,
        date(2024, 2, 8),
    )

    # Then: query and output remain fixed to qualified current-schema evidence.
    query = collection.queries[0]
    assert query["schema_manifest_id"] == schema_id
    assert query["quality_status"] == "ACCEPTED"
    assert query["exchange"] == "SSE"
    assert calendar.next_open_date == date(2024, 2, 19)
