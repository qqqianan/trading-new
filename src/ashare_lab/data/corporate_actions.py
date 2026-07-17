"""Point-in-time dividend lifecycle events."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum, unique
from zoneinfo import ZoneInfo

from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.tushare_client import Scalar

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRANSFORM_NAME = "dividend_row_to_pit_events"
_TRANSFORM_VERSION = "1.0.0"


@unique
class DividendEventType(StrEnum):
    """Closed dividend facts exposed at distinct announcement stages."""

    PLAN_ANNOUNCED = "PLAN_ANNOUNCED"
    IMPLEMENTATION_ANNOUNCED = "IMPLEMENTATION_ANNOUNCED"


@dataclass(frozen=True, slots=True)
class DividendEvent:
    """One immutable dividend transition without future-stage fields."""

    event_id: str
    ts_code: str
    end_date: str
    event_type: DividendEventType
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    div_proc: str | None
    stk_div: float | None
    stk_bo_rate: float | None
    stk_co_rate: float | None
    cash_div: float | None
    cash_div_tax: float | None
    record_date: str | None
    ex_date: str | None
    pay_date: str | None
    div_listdate: str | None
    source_snapshot_id: str
    source_row_sha256: str
    input_schema_manifest_id: str
    schema_manifest_id: str
    transform_name: str
    transform_version: str
    quality_status: str
    quality_report_id: str


@dataclass(frozen=True, slots=True)
class _EventTiming:
    effective_at: datetime
    available_at: datetime


def build_dividend_events(record: CanonicalRecord) -> tuple[DividendEvent, ...]:
    """Split one mixed provider row into stage-safe announcement events."""
    payload = dict(record.business_fields)
    events: list[DividendEvent] = []
    announcement = _optional_string(payload, "ann_date")
    if announcement is not None:
        announced_at = _announcement_time(announcement)
        events.append(
            _event(
                record,
                payload,
                DividendEventType.PLAN_ANNOUNCED,
                _EventTiming(announced_at, min(announced_at, record.ingested_at)),
                (None, None, None, None),
            )
        )
    implementation = _optional_string(payload, "imp_ann_date")
    if implementation is not None:
        implemented_at = _announcement_time(implementation)
        events.append(
            _event(
                record,
                payload,
                DividendEventType.IMPLEMENTATION_ANNOUNCED,
                _EventTiming(implemented_at, min(implemented_at, record.ingested_at)),
                _implementation_fields(payload),
            )
        )
    return tuple(events)


def select_dividend_events(
    events: tuple[DividendEvent, ...],
    decision_time: datetime,
) -> tuple[DividendEvent, ...]:
    """Return only accepted dividend facts visible at one aware decision time."""
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        msg = "decision_time must be timezone-aware"
        raise ValueError(msg)
    return tuple(
        event
        for event in events
        if event.quality_status == "ACCEPTED"
        and event.effective_at <= decision_time
        and event.available_at <= decision_time
    )


def _event(
    record: CanonicalRecord,
    payload: dict[str, Scalar],
    event_type: DividendEventType,
    timing: _EventTiming,
    implementation: tuple[str | None, str | None, str | None, str | None],
) -> DividendEvent:
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|{event_type.value}|"
        f"{record.schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    event_id = f"dividend_event_{hashlib.sha256(identity.encode()).hexdigest()}"
    quality_id = f"quality_{hashlib.sha256(event_id.encode()).hexdigest()}"
    return DividendEvent(
        event_id=event_id,
        ts_code=_required_string(payload, "ts_code"),
        end_date=_required_string(payload, "end_date"),
        event_type=event_type,
        effective_at=timing.effective_at,
        available_at=timing.available_at,
        ingested_at=record.ingested_at,
        div_proc=_optional_string(payload, "div_proc"),
        stk_div=_optional_float(payload, "stk_div"),
        stk_bo_rate=_optional_float(payload, "stk_bo_rate"),
        stk_co_rate=_optional_float(payload, "stk_co_rate"),
        cash_div=_optional_float(payload, "cash_div"),
        cash_div_tax=_optional_float(payload, "cash_div_tax"),
        record_date=implementation[0],
        ex_date=implementation[1],
        pay_date=implementation[2],
        div_listdate=implementation[3],
        source_snapshot_id=record.source_snapshot_id,
        source_row_sha256=record.source_row_sha256,
        input_schema_manifest_id=record.schema_manifest_id,
        schema_manifest_id=record.schema_manifest_id,
        transform_name=_TRANSFORM_NAME,
        transform_version=_TRANSFORM_VERSION,
        quality_status="ACCEPTED",
        quality_report_id=quality_id,
    )


def _implementation_fields(
    payload: dict[str, Scalar],
) -> tuple[str | None, str | None, str | None, str | None]:
    return (
        _optional_string(payload, "record_date"),
        _optional_string(payload, "ex_date"),
        _optional_string(payload, "pay_date"),
        _optional_string(payload, "div_listdate"),
    )


def _required_string(payload: dict[str, Scalar], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    detail = f"dividend source field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _optional_string(payload: dict[str, Scalar], field: str) -> str | None:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    if value is None:
        return None
    detail = f"dividend source field is invalid: {field}"
    raise SchemaContractError(detail)


def _optional_float(payload: dict[str, Scalar], field: str) -> float | None:
    value = payload.get(field)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    detail = f"dividend source field is invalid: {field}"
    raise SchemaContractError(detail)


def _announcement_time(raw_date: str) -> datetime:
    parsed = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
    return datetime.combine(parsed, time(18, 0), _SHANGHAI)
