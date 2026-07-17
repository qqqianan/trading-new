from types import TracebackType
from typing import Self

import pytest

from ashare_lab.data import financial_progress
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.financial_store import income_batch_artifact_id
from ashare_lab.data.schema_registry import SchemaRegistry


class Collection:
    def __init__(self, documents: list[BsonDocument], codes: list[str] | None = None) -> None:
        self.documents = documents
        self.codes = codes or []

    def distinct(self, _field: str, _query: BsonDocument) -> list[str]:
        return self.codes

    def find(self, _query: BsonDocument) -> list[BsonDocument]:
        return self.documents

    def find_one(
        self, query: BsonDocument, _projection: BsonDocument | None = None
    ) -> BsonDocument | None:
        return next(
            (d for d in self.documents if all(d.get(k) == v for k, v in query.items())),
            None,
        )


class Database:
    def __init__(self) -> None:
        canonical = "canonical_income"
        batch = income_batch_artifact_id(canonical)
        self.items = {
            "pit_security_events": Collection([], ["600000.SH", "000001.SZ"]),
            "meta_source_snapshots": Collection(
                [
                    {
                        "snapshot_id": "snap",
                        "request_params_canonical": (
                            '{"end_date":"20260716","start_date":"20200101","ts_code":"000001.SZ"}'
                        ),
                    }
                ]
            ),
            "meta_lineage_edges": Collection(
                [
                    {
                        "upstream_artifact_id": "snap",
                        "output_schema_id": "schema",
                        "transform_name": "tushare_raw_to_canonical",
                        "downstream_artifact_id": canonical,
                    },
                    {
                        "upstream_artifact_id": canonical,
                        "downstream_artifact_id": batch,
                        "output_schema_id": "schema",
                    },
                ]
            ),
            "meta_quality_reports": Collection([{"artifact_id": batch, "passed": True}]),
        }

    def __getitem__(self, name: str) -> Collection:
        return self.items[name]


class Mongo:
    database = Database()

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


def test_financial_progress_loads_lifecycle_codes_and_complete_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: isolated universe and financial evidence collections.
    monkeypatch.setattr(financial_progress, "MongoClient", Mongo)
    registry = SchemaRegistry.__new__(SchemaRegistry)
    registry.__dict__["_manifest_id"] = "schema"

    # When: both progress views are loaded.
    codes = financial_progress.load_income_security_codes()
    complete = financial_progress.load_completed_income_codes(registry, "20200101", "20260716")

    # Then: codes are sorted and only the proven range is complete.
    assert codes == ("000001.SZ", "600000.SH")
    assert complete == frozenset({"000001.SZ"})
