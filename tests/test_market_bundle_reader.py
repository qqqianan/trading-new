from datetime import UTC, date, datetime

import pytest

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.research.features.market.mongo_contracts import MarketBundleConflictError
from ashare_lab.research.features.market.mongo_reader import MongoMarketBundleReader


class Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.documents = documents
        self.queries: list[BsonDocument] = []
        self.projections: list[BsonDocument] = []

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        self.queries.append(query)
        assert projection is not None
        self.projections.append(projection)
        return self.documents


class Database:
    name = "ashare_quant"

    def __init__(self, collections: dict[str, Collection]) -> None:
        self.collections = collections

    def __getitem__(self, name: str) -> Collection:
        return self.collections[name]


def test_market_bundle_reader_joins_five_governed_chains_and_converts_units() -> None:
    # Given: one complete accepted daily bundle reached through Raw snapshot identities.
    database = _database()

    # When: the date slice crosses the read-only market bundle boundary.
    result = MongoMarketBundleReader(database).read(
        date(2026, 7, 16),
        date(2026, 7, 16),
        "schema_market",
    )

    # Then: the complete bundle is typed, PIT-aware, and normalized to yuan/shares.
    assert result.rejections == ()
    assert len(result.observations) == 1
    row = result.observations[0]
    assert row.amount_cny == 25_000_000.0
    assert row.bar.volume == 100_000
    assert row.bar.limit_up == 11.0
    assert row.total_mv_ten_thousand_cny == 1_000_000.0
    assert row.bar.available_at.hour == 16
    assert len(row.source_artifact_ids) == 4
    daily_projection = database["canonical_daily_bar"].projections[0]
    assert set(daily_projection) == {
        "_id",
        "record_id",
        "ts_code",
        "trade_date",
        "available_at",
        "quality_status",
        "schema_manifest_id",
        "source_snapshot_id",
        "source_row_sha256",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "vol",
        "amount",
    }


def test_market_bundle_reader_records_missing_required_adjustment_factor() -> None:
    # Given: a daily bar whose required same-day adjustment factor is absent.
    database = _database(adjustments=())

    # When: bundle completeness is adjudicated.
    result = MongoMarketBundleReader(database).read(
        date(2026, 7, 16),
        date(2026, 7, 16),
        "schema_market",
    )

    # Then: the row is not silently dropped or partially treated as valid.
    assert result.observations == ()
    assert result.rejections[0].reason == "MISSING_ADJUSTMENT_FACTOR"


def test_market_bundle_reader_rejects_conflicting_daily_replays() -> None:
    # Given: one natural key with two accepted but materially different closes.
    first = _daily_document("record_daily_001", close=10.0)
    conflict = _daily_document("record_daily_002", close=10.5)
    database = _database(daily=(first, conflict))

    # When / Then: arbitrary record ordering cannot select the research truth.
    with pytest.raises(MarketBundleConflictError, match="market_bundle_conflict"):
        MongoMarketBundleReader(database).read(
            date(2026, 7, 16),
            date(2026, 7, 16),
            "schema_market",
        )


def _database(
    *,
    daily: tuple[BsonDocument, ...] | None = None,
    adjustments: tuple[BsonDocument, ...] | None = None,
) -> Database:
    snapshots: tuple[BsonDocument, ...] = tuple(
        {
            "snapshot_id": f"snapshot_{endpoint}",
            "endpoint": endpoint,
            "request_params_canonical": '{"trade_date":"20260716"}',
            "schema_manifest_id": "schema_market",
            "status": "ACCEPTED",
        }
        for endpoint in ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d")
    )
    return Database(
        {
            "meta_source_snapshots": Collection(snapshots),
            "canonical_daily_bar": Collection(daily or (_daily_document("record_daily_001"),)),
            "canonical_adjustment_factor": Collection(
                adjustments
                if adjustments is not None
                else (_base_document("record_adj_001", "snapshot_adj_factor", {"adj_factor": 1.2}),)
            ),
            "canonical_daily_valuation": Collection(
                (
                    _base_document(
                        "record_valuation_001",
                        "snapshot_daily_basic",
                        {
                            "turnover_rate": 2.0,
                            "total_mv": 1_000_000.0,
                            "pe_ttm": 20.0,
                            "pb": 4.0,
                            "ps_ttm": 10.0,
                            "dv_ttm": 3.0,
                        },
                    ),
                )
            ),
            "canonical_daily_price_limit": Collection(
                (
                    _base_document(
                        "record_limit_001",
                        "snapshot_stk_limit",
                        {"up_limit": 11.0, "down_limit": 9.0},
                    ),
                )
            ),
            "canonical_suspension_event": Collection(()),
        }
    )


def _daily_document(record_id: str, *, close: float = 10.0) -> BsonDocument:
    return _base_document(
        record_id,
        "snapshot_daily",
        {
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": close,
            "pre_close": 9.9,
            "vol": 1_000.0,
            "amount": 25_000.0,
        },
    )


def _base_document(
    record_id: str,
    snapshot_id: str,
    fields: BsonDocument,
) -> BsonDocument:
    document: BsonDocument = {
        "_id": record_id,
        "record_id": record_id,
        "ts_code": "000001.SZ",
        "trade_date": "20260716",
        "available_at": datetime(2026, 7, 16, 8, tzinfo=UTC),
        "quality_status": "ACCEPTED",
        "schema_manifest_id": "schema_market",
        "source_snapshot_id": snapshot_id,
        "source_row_sha256": "a" * 64,
    }
    document.update(fields)
    return document
