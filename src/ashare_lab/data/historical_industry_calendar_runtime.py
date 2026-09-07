"""Read-only canonical trade-calendar adapter for industry source admission."""

from datetime import date, timedelta
from pathlib import Path

from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.historical_industry_calendar import (
    HistoricalIndustryCalendarError,
    HistoricalIndustryCalendarEvidence,
    HistoricalIndustryCalendarRow,
    build_historical_industry_calendar,
)
from ashare_lab.data.schema_registry import SchemaRegistry

_SEARCH_DAYS = 31


def load_historical_industry_calendar(
    project_root: Path,
    publication_date: date,
) -> HistoricalIndustryCalendarEvidence:
    """Read exact-schema accepted SSE rows without mutating market data."""
    market_schema_id = SchemaRegistry.load(
        project_root / "schemas" / "tushare_p0_v1.json"
    ).manifest_id
    end_date = publication_date + timedelta(days=_SEARCH_DAYS)
    query: BsonDocument = {
        "schema_manifest_id": market_schema_id,
        "quality_status": "ACCEPTED",
        "exchange": "SSE",
        "cal_date": {
            "$gte": publication_date.strftime("%Y%m%d"),
            "$lte": end_date.strftime("%Y%m%d"),
        },
    }
    projection: BsonDocument = {
        "_id": 0,
        "cal_date": 1,
        "exchange": 1,
        "is_open": 1,
        "quality_status": 1,
        "schema_manifest_id": 1,
        "source_snapshot_id": 1,
        "source_row_sha256": 1,
    }
    settings = DataSettings()
    try:
        with MongoClient[BsonDocument](
            settings.mongodb_uri,
            serverSelectionTimeoutMS=8_000,
        ) as client:
            rows = tuple(
                HistoricalIndustryCalendarRow.model_validate(document)
                for document in client[settings.mongodb_database]["canonical_trade_calendar"].find(
                    query, projection
                )
            )
    except (PyMongoError, ValidationError) as error:
        detail = "canonical trade calendar cannot cross its typed read boundary"
        raise HistoricalIndustryCalendarError(detail) from error
    return build_historical_industry_calendar(rows, publication_date=publication_date)
