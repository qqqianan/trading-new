"""Point-in-time index constituent weight events."""

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Final

from ashare_lab.data.canonical import CanonicalBatch, CanonicalRecord
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.tushare_client import Scalar

_TRANSFORM_NAME = "index_weight_row_to_pit_event"
_TRANSFORM_VERSION = "1.0.0"
_PROVIDER_ROW_CAP: Final = 1_000
_MIN_WEIGHT_SUM: Final = 95.0
_MAX_WEIGHT_SUM: Final = 105.0


@unique
class IndexWeightEventType(StrEnum):
    """Closed index-weight publication transitions."""

    PUBLISHED = "INDEX_WEIGHT_PUBLISHED"


@dataclass(frozen=True, slots=True)
class IndexWeightEvent:
    """One immutable constituent weight known after an index close."""

    event_id: str
    event_type: IndexWeightEventType
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    source_snapshot_id: str
    source_row_sha256: str
    input_schema_manifest_id: str
    schema_manifest_id: str
    transform_name: str
    transform_version: str
    quality_status: str
    quality_report_id: str
    index_code: str
    con_code: str
    trade_date: str
    weight: float


def build_index_weight_event(record: CanonicalRecord) -> IndexWeightEvent:
    """Project one quarantined canonical row into an accepted PIT event."""
    payload = dict(record.business_fields)
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|"
        f"{record.schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    event_id = f"index_weight_event_{hashlib.sha256(identity.encode()).hexdigest()}"
    return IndexWeightEvent(
        event_id=event_id,
        event_type=IndexWeightEventType.PUBLISHED,
        effective_at=record.available_at,
        available_at=record.available_at,
        ingested_at=record.ingested_at,
        source_snapshot_id=record.source_snapshot_id,
        source_row_sha256=record.source_row_sha256,
        input_schema_manifest_id=record.schema_manifest_id,
        schema_manifest_id=record.schema_manifest_id,
        transform_name=_TRANSFORM_NAME,
        transform_version=_TRANSFORM_VERSION,
        quality_status="ACCEPTED",
        quality_report_id=f"quality_{hashlib.sha256(event_id.encode()).hexdigest()}",
        index_code=_required_string(payload, "index_code"),
        con_code=_required_string(payload, "con_code"),
        trade_date=_required_string(payload, "trade_date"),
        weight=_required_weight(payload),
    )


def validate_index_weight_batch(batch: CanonicalBatch) -> None:
    """Reject ambiguous, truncated, or materially incomplete monthly weights."""
    if not batch.records:
        return
    events = tuple(build_index_weight_event(record) for record in batch.records)
    dates = {event.trade_date for event in events}
    codes = {event.index_code for event in events}
    if len(dates) != 1 or len(codes) != 1:
        detail = "index-weight month must contain one index and one publication date"
        raise SchemaContractError(detail)
    index_code = events[0].index_code
    if len(events) >= _PROVIDER_ROW_CAP and index_code != "000852.SH":
        detail = "index-weight response reached provider row cap"
        raise SchemaContractError(detail)
    total_weight = sum(event.weight for event in events)
    if not _MIN_WEIGHT_SUM <= total_weight <= _MAX_WEIGHT_SUM:
        detail = f"index-weight sum is incomplete: {total_weight:.6f}"
        raise SchemaContractError(detail)


def _required_string(payload: dict[str, Scalar], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    detail = f"index-weight source field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _required_weight(payload: dict[str, Scalar]) -> float:
    value = payload.get("weight")
    if isinstance(value, int | float) and not isinstance(value, bool):
        weight = float(value)
        if math.isfinite(weight) and weight > 0:
            return weight
    detail = "index-weight source field is missing or invalid: weight"
    raise SchemaContractError(detail)
