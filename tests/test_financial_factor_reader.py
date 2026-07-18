from datetime import UTC, datetime

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.research.features.financial.mongo_reader import MongoFinancialFactorReader


class Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.documents = documents
        self.queries: list[BsonDocument] = []

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        assert projection is not None
        self.queries.append(query)
        return self.documents


class Database:
    name = "ashare_quant"

    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.collection = Collection(documents)

    def __getitem__(self, name: str) -> Collection:
        assert name == "pit_financial_indicators"
        return self.collection


def test_financial_factor_reader_loads_only_typed_pit_versions() -> None:
    # Given: one current-schema accepted financial publication.
    database = Database((_document(),))

    # When: the bounded PIT reader loads evidence visible by the cutoff.
    rows = MongoFinancialFactorReader(database).read(
        datetime(2026, 7, 10, 10, tzinfo=UTC),
        "schema_financial",
    )

    # Then: the source version and six raw metrics remain traceable.
    assert len(rows) == 1
    assert rows[0].event_id == "event_001"
    assert rows[0].report_period == "20260331"
    assert rows[0].available_at.hour == 18
    assert rows[0].q_netprofit_yoy == 15.0
    assert database.collection.queries[0]["quality_status"] == "ACCEPTED"


def _document() -> BsonDocument:
    return {
        "_id": "event_001",
        "event_id": "event_001",
        "ts_code": "000001.SZ",
        "available_at": datetime(2026, 7, 10, 10, tzinfo=UTC),
        "end_date": "20260331",
        "update_flag": "1",
        "roe": 8.0,
        "grossprofit_margin": 30.0,
        "ocf_to_debt": 0.2,
        "debt_to_assets": 50.0,
        "q_sales_yoy": 12.0,
        "q_netprofit_yoy": 15.0,
        "source_snapshot_id": "snapshot_001",
        "source_row_sha256": "a" * 64,
        "schema_manifest_id": "schema_financial",
        "quality_status": "ACCEPTED",
    }
