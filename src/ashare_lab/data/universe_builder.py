"""Build PIT security events from governed canonical source records."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.universe import SecurityEvent, SecurityEventType

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRANSFORM_NAME = "security_master_to_pit_events"
_TRANSFORM_VERSION = "1.1.1"


@dataclass(frozen=True, slots=True)
class _EventValues:
    effective_at: datetime
    available_at: datetime
    name: str | None
    is_st: bool | None


@dataclass(frozen=True, slots=True)
class _EventOrigin:
    source_endpoint: str
    input_schema_manifest_id: str
    output_schema_manifest_id: str


def build_lifecycle_events(record: CanonicalRecord) -> tuple[SecurityEvent, ...]:
    """Derive listing, optional delisting, and observed current-name events."""
    payload = dict(record.business_fields)
    ts_code = _required_string(payload, "ts_code")
    origin = _EventOrigin("stock_basic", record.schema_manifest_id, record.schema_manifest_id)
    listed_at = _date_time(_required_string(payload, "list_date"), time(9, 25))
    events = [
        _event(
            record,
            ts_code,
            SecurityEventType.LISTED,
            _EventValues(listed_at, min(listed_at, record.available_at), None, None),
            origin,
        )
    ]
    raw_delist_date = payload.get("delist_date")
    if isinstance(raw_delist_date, str):
        delisted_at = _date_time(raw_delist_date, time(9, 25))
        events.append(
            _event(
                record,
                ts_code,
                SecurityEventType.DELISTED,
                _EventValues(
                    delisted_at,
                    min(delisted_at, record.available_at),
                    None,
                    None,
                ),
                origin,
            )
        )
    current_name = _required_string(payload, "name")
    events.append(
        _event(
            record,
            ts_code,
            SecurityEventType.NAME_STATUS,
            _EventValues(
                record.available_at,
                record.available_at,
                current_name,
                _is_st_name(current_name),
            ),
            origin,
        )
    )
    return tuple(events)


def build_name_status_event(record: CanonicalRecord) -> SecurityEvent:
    """Derive one historically announced name and ST-state event."""
    payload = dict(record.business_fields)
    ts_code = _required_string(payload, "ts_code")
    name = _required_string(payload, "name")
    origin = _EventOrigin("namechange", record.schema_manifest_id, record.schema_manifest_id)
    return _event(
        record,
        ts_code,
        SecurityEventType.NAME_STATUS,
        _EventValues(record.event_time, record.available_at, name, _is_st_name(name)),
        origin,
    )


def build_first_trade_event(
    record: CanonicalRecord,
    output_schema_manifest_id: str,
) -> SecurityEvent:
    """Use the first accepted daily bar as conservative listing evidence."""
    payload = dict(record.business_fields)
    ts_code = _required_string(payload, "ts_code")
    return _event(
        record,
        ts_code,
        SecurityEventType.FIRST_TRADED,
        _EventValues(record.event_time, record.available_at, None, None),
        _EventOrigin("daily", record.schema_manifest_id, output_schema_manifest_id),
    )


def _event(
    record: CanonicalRecord,
    ts_code: str,
    event_type: SecurityEventType,
    values: _EventValues,
    origin: _EventOrigin,
) -> SecurityEvent:
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|{event_type.value}|"
        f"{origin.output_schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    event_id = f"universe_event_{hashlib.sha256(identity.encode()).hexdigest()}"
    quality_id = f"quality_{hashlib.sha256(event_id.encode()).hexdigest()}"
    return SecurityEvent(
        event_id=event_id,
        ts_code=ts_code,
        event_type=event_type,
        effective_at=values.effective_at,
        available_at=values.available_at,
        ingested_at=record.ingested_at,
        name=values.name,
        is_st=values.is_st,
        source_endpoint=origin.source_endpoint,
        source_snapshot_id=record.source_snapshot_id,
        source_row_sha256=record.source_row_sha256,
        input_schema_manifest_id=origin.input_schema_manifest_id,
        schema_manifest_id=origin.output_schema_manifest_id,
        transform_name=_TRANSFORM_NAME,
        transform_version=_TRANSFORM_VERSION,
        quality_status="ACCEPTED",
        quality_report_id=quality_id,
    )


def _required_string(payload: dict[str, str | int | float | bool | None], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    detail = f"universe event source field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _date_time(raw_date: str, at: time) -> datetime:
    parsed = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
    return datetime.combine(parsed, at, _SHANGHAI)


def _is_st_name(name: str) -> bool:
    return "ST" in name.upper()
