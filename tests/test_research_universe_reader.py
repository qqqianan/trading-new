from datetime import UTC, date, datetime

import pytest

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.research.universe.mongo_reader import (
    MongoUniversePanelReader,
    UniverseReaderError,
)


class Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.documents = documents
        self.queries: list[BsonDocument] = []

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        self.queries.append(query)
        assert projection is not None
        return self.documents


class Database:
    name = "ashare_quant"

    def __init__(self, collections: dict[str, Collection]) -> None:
        self.collections = collections

    def __getitem__(self, name: str) -> Collection:
        return self.collections[name]


class LegacyDatabase(Database):
    name = "legacy"


def test_mongo_universe_reader_normalizes_governed_rows_and_amount_units() -> None:
    # Given: exact-schema accepted calendar, lifecycle, and daily Mongo documents.
    database = Database(
        {
            "canonical_trade_calendar": Collection(
                (
                    {
                        "cal_date": "20260716",
                        "is_open": 1,
                        "quality_status": "ACCEPTED",
                        "schema_manifest_id": "schema_market",
                    },
                )
            ),
            "pit_security_events": Collection((_security_event_document(),)),
            "canonical_daily_bar": Collection(
                (
                    {
                        "record_id": "record_daily_001",
                        "ts_code": "000001.SZ",
                        "trade_date": "20260716",
                        "available_at": datetime(2026, 7, 16, 8, tzinfo=UTC),
                        "amount": 25_000.0,
                        "quality_status": "ACCEPTED",
                        "schema_manifest_id": "schema_market",
                    },
                )
            ),
        }
    )

    # When: the bounded evidence slice crosses the Mongo trust boundary.
    evidence = MongoUniversePanelReader(database).read(
        date(2026, 7, 16),
        date(2026, 7, 16),
        "schema_market",
        "schema_universe",
    )

    # Then: dates, PIT events, RMB amounts, and Shanghai availability are normalized.
    assert evidence.open_dates == (date(2026, 7, 16),)
    assert evidence.events[0].event_id == "event_001"
    assert evidence.observations[0].amount_cny == 25_000_000.0
    assert evidence.observations[0].available_at.hour == 16


def test_mongo_universe_reader_rejects_non_governed_database() -> None:
    # Given: a database outside the fixed ashare_quant boundary.
    database = LegacyDatabase({})

    # When / Then: no legacy collection can enter research materialization.
    with pytest.raises(UniverseReaderError, match="requires ashare_quant"):
        MongoUniversePanelReader(database)


def _security_event_document() -> BsonDocument:
    observed = datetime(2026, 7, 16, 1, 25, tzinfo=UTC)
    return {
        "_id": "event_001",
        "event_id": "event_001",
        "ts_code": "000001.SZ",
        "event_type": "LISTED",
        "effective_at": observed,
        "available_at": observed,
        "ingested_at": observed,
        "name": None,
        "is_st": None,
        "source_endpoint": "stock_basic",
        "source_snapshot_id": "snapshot_001",
        "source_row_sha256": "a" * 64,
        "input_schema_manifest_id": "schema_universe",
        "schema_manifest_id": "schema_universe",
        "transform_name": "security_master_to_pit_events",
        "transform_version": "1.1.1",
        "quality_status": "ACCEPTED",
        "quality_report_id": "quality_001",
    }
