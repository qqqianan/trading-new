"""Pydantic trust-boundary documents for the five daily market chains."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from ashare_lab.data.bson_types import BsonDocument

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class SnapshotDocument(BaseModel):
    """Accepted Raw snapshot and its canonical request parameters."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    endpoint: str
    request_params_canonical: str
    schema_manifest_id: str
    status: str


class DateParams(BaseModel):
    """Closed query parameters shared by all five daily endpoints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_date: str


class CanonicalDocument(BaseModel):
    """Shared immutable canonical envelope fields."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    record_id: str
    ts_code: str
    trade_date: str
    available_at: datetime
    quality_status: str
    schema_manifest_id: str
    source_snapshot_id: str
    source_row_sha256: str

    @property
    def key(self) -> tuple[str, date]:
        """Return the typed natural symbol-date key."""
        return self.ts_code, parse_date(self.trade_date)

    @property
    def available_shanghai(self) -> datetime:
        """Restore PyMongo UTC values to the research timezone."""
        value = self.available_at
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.astimezone(_SHANGHAI)


class DailyDocument(CanonicalDocument):
    """Execution-price and amount fields from accepted daily bars."""

    open: float
    high: float
    low: float
    close: float
    pre_close: float | None
    vol: float
    amount: float


class AdjustmentDocument(CanonicalDocument):
    """Same-day point-in-time adjustment factor."""

    adj_factor: float


class ValuationDocument(CanonicalDocument):
    """Nullable same-day turnover, size, and valuation fields."""

    turnover_rate: float | None = None
    total_mv: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    ps_ttm: float | None = None
    dv_ttm: float | None = None


class LimitDocument(CanonicalDocument):
    """Raw execution limits known before the session open."""

    up_limit: float
    down_limit: float


class SuspensionDocument(CanonicalDocument):
    """Sparse suspension or resumption event."""

    suspend_type: str


def snapshot_date(document: BsonDocument) -> tuple[SnapshotDocument, date]:
    """Parse one snapshot and its structured trade date."""
    snapshot = SnapshotDocument.model_validate(document)
    params = DateParams.model_validate_json(snapshot.request_params_canonical)
    return snapshot, parse_date(params.trade_date)


def parse_date(value: str) -> date:
    """Parse provider YYYYMMDD without locale ambiguity."""
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
