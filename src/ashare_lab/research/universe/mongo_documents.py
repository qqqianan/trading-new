"""Typed parsing of Mongo universe materialization documents."""

from datetime import UTC, date, datetime
from typing import Final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.universe import SecurityEvent
from ashare_lab.data.universe_store import security_event_from_document
from ashare_lab.research.universe.models import UniverseMarketObservation

_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
EVENT_FIELDS: Final = (
    "_id",
    "event_id",
    "ts_code",
    "event_type",
    "effective_at",
    "available_at",
    "ingested_at",
    "name",
    "is_st",
    "source_endpoint",
    "source_snapshot_id",
    "source_row_sha256",
    "input_schema_manifest_id",
    "schema_manifest_id",
    "transform_name",
    "transform_version",
    "quality_status",
    "quality_report_id",
)
DAILY_FIELDS: Final = (
    "record_id",
    "ts_code",
    "trade_date",
    "available_at",
    "amount",
    "quality_status",
    "schema_manifest_id",
)


class CalendarDocument(BaseModel):
    """Accepted trade-calendar fields used by the weekly clock."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    cal_date: str
    is_open: int
    quality_status: str
    schema_manifest_id: str


class DailyDocument(BaseModel):
    """Accepted daily fields used by admission rules."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    record_id: str
    ts_code: str
    trade_date: str
    available_at: datetime
    amount: float
    quality_status: str
    schema_manifest_id: str


def security_event(document: BsonDocument) -> SecurityEvent:
    """Parse one closed lifecycle event through its existing trust boundary."""
    return security_event_from_document(document)


def market_observation(document: BsonDocument) -> tuple[UniverseMarketObservation, str]:
    """Normalize Tushare thousand-yuan amount and retain its schema identity."""
    parsed = DailyDocument.model_validate(document)
    observation = UniverseMarketObservation(
        symbol=parsed.ts_code,
        trading_date=parse_date(parsed.trade_date),
        available_at=restore_mongo_time(parsed.available_at),
        amount_cny=parsed.amount * 1_000.0,
        quality_status=parsed.quality_status,
        source_artifact_id=parsed.record_id,
    )
    return observation, parsed.schema_manifest_id


def parse_date(value: str) -> date:
    """Parse a provider YYYYMMDD value without locale ambiguity."""
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def restore_mongo_time(value: datetime) -> datetime:
    """Restore PyMongo UTC datetimes to the research timezone."""
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.astimezone(_SHANGHAI)
