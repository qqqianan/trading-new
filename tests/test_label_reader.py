from datetime import UTC, date, datetime

from pydantic import TypeAdapter

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.research.labels.mongo_benchmark_reader import (
    BenchmarkSnapshotBoundary,
    read_dataset_benchmark_observations,
)
from ashare_lab.research.labels.mongo_reader import MongoLabelEvidenceReader

_SNAPSHOT_IDS = TypeAdapter(tuple[str, ...])
_SNAPSHOT_ID = TypeAdapter(str)


class Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self._documents = documents

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        assert projection is not None
        return tuple(document for document in self._documents if _matches(document, query))


class Database:
    name = "ashare_quant"

    def __init__(self, collections: dict[str, tuple[BsonDocument, ...]]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> Collection:
        return Collection(self._collections.get(name, ()))


def test_label_reader_joins_exact_schema_price_constraint_and_benchmark() -> None:
    # Given: accepted market snapshots and one exact benchmark range snapshot.
    database = Database(
        {
            "meta_source_snapshots": (
                _snapshot("snap_daily", "daily", '{"trade_date":"20250106"}', "schema_market"),
                _snapshot("snap_limit", "stk_limit", '{"trade_date":"20250106"}', "schema_market"),
                _snapshot(
                    "snap_benchmark",
                    "index_daily",
                    '{"end_date":"20250131","start_date":"20250101","ts_code":"000905.SH"}',
                    "schema_benchmark",
                ),
            ),
            "canonical_daily_bar": (_daily("000001.SZ", "snap_daily", "schema_market"),),
            "canonical_daily_price_limit": (_limit(),),
            "canonical_index_daily_bar": (
                _daily("000905.SH", "snap_benchmark", "schema_benchmark"),
            ),
        }
    )
    reader = MongoLabelEvidenceReader(database)

    # When: both bounded read capabilities load the fixed session.
    stocks = reader.stock_observations(
        date(2025, 1, 6),
        date(2025, 1, 6),
        "schema_market",
    )
    benchmark = reader.benchmark_observations(
        date(2025, 1, 6),
        date(2025, 1, 6),
        "000905.SH",
        "schema_benchmark",
    )

    # Then: raw open, limit, clocks, and all source identities remain exact.
    assert len(stocks) == 1
    assert stocks[0].open_price == 10.0
    assert stocks[0].up_limit == 11.0
    assert stocks[0].price_source_snapshot_id == "snap_daily"
    assert stocks[0].constraint_source_snapshot_id == "snap_limit"
    assert benchmark[0].open_price == 10.0
    assert benchmark[0].source_snapshot_id == "snap_benchmark"


def test_benchmark_reader_restricts_raw_snapshots_to_dataset_allowlist() -> None:
    # Given: two accepted benchmark snapshots but only one belongs to DatasetSpec.
    allowed = _daily("000905.SH", "snap_allowed", "schema_benchmark")
    excluded = dict(_daily("000905.SH", "snap_excluded", "schema_benchmark"))
    excluded["record_id"] = "record_excluded"
    database = Database(
        {
            "meta_source_snapshots": (
                _snapshot(
                    "snap_allowed",
                    "index_daily",
                    '{"end_date":"20250131","start_date":"20250101","ts_code":"000905.SH"}',
                    "schema_benchmark",
                ),
                _snapshot(
                    "snap_excluded",
                    "index_daily",
                    '{"end_date":"20250131","start_date":"20250101","ts_code":"000905.SH"}',
                    "schema_benchmark",
                ),
            ),
            "canonical_index_daily_bar": (allowed, excluded),
        }
    )

    # When: the benchmark is read through the frozen source snapshot boundary.
    result = read_dataset_benchmark_observations(
        database,
        date(2025, 1, 6),
        date(2025, 1, 6),
        "000905.SH",
        BenchmarkSnapshotBoundary("schema_benchmark", ("snap_allowed",)),
    )

    # Then: the later accepted snapshot cannot replace frozen benchmark evidence.
    assert tuple(item.source_snapshot_id for item in result) == ("snap_allowed",)


def _matches(document: BsonDocument, query: BsonDocument) -> bool:
    expected_schema = query.get("schema_manifest_id")
    expected_quality = query.get("quality_status")
    snapshot_query = query.get("source_snapshot_id", query.get("snapshot_id"))
    match snapshot_query:
        case {"$in": values}:
            allowed = _SNAPSHOT_IDS.validate_python(values)
            document_id = _SNAPSHOT_ID.validate_python(
                document.get("source_snapshot_id", document.get("snapshot_id"))
            )
            snapshot_matches = document_id in allowed
        case _:
            snapshot_matches = True
    return (
        snapshot_matches
        and document.get("schema_manifest_id") == expected_schema
        and (expected_quality is None or document.get("quality_status") == expected_quality)
    )


def _snapshot(
    snapshot_id: str,
    endpoint: str,
    params: str,
    schema: str,
) -> BsonDocument:
    return {
        "snapshot_id": snapshot_id,
        "endpoint": endpoint,
        "request_params_canonical": params,
        "schema_manifest_id": schema,
        "status": "ACCEPTED",
    }


def _daily(symbol: str, snapshot: str, schema: str) -> BsonDocument:
    return {
        "record_id": f"record_{symbol}",
        "ts_code": symbol,
        "trade_date": "20250106",
        "available_at": datetime(2025, 1, 6, 10, tzinfo=UTC),
        "quality_status": "ACCEPTED",
        "schema_manifest_id": schema,
        "source_snapshot_id": snapshot,
        "source_row_sha256": "a" * 64,
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "pre_close": 9.9,
        "vol": 100.0,
        "amount": 1_000.0,
    }


def _limit() -> BsonDocument:
    return {
        "record_id": "record_limit",
        "ts_code": "000001.SZ",
        "trade_date": "20250106",
        "available_at": datetime(2025, 1, 5, 18, tzinfo=UTC),
        "quality_status": "ACCEPTED",
        "schema_manifest_id": "schema_market",
        "source_snapshot_id": "snap_limit",
        "source_row_sha256": "b" * 64,
        "up_limit": 11.0,
        "down_limit": 9.0,
    }
