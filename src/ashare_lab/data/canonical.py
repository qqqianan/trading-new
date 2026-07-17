"""Pure Raw-to-canonical conversion with point-in-time and field lineage."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from ashare_lab.data.schema_registry import EndpointSchema, SchemaContractError
from ashare_lab.data.snapshots import SnapshotBatch
from ashare_lab.data.tushare_client import Scalar

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRANSFORM_NAME = "tushare_raw_to_canonical"
_TRANSFORM_VERSION = "1.1.2"
_PIT_SPLIT_REQUIRED: Final[frozenset[str]] = frozenset(
    {
        "balancesheet",
        "cashflow",
        "dividend",
        "fina_indicator",
        "income",
        "income_vip",
        "index_member",
        "index_weight",
        "stock_basic",
    }
)


@dataclass(frozen=True, slots=True)
class CanonicalRecord:
    """One normalized record with source, time, and quality evidence."""

    record_id: str
    schema_manifest_id: str
    source_snapshot_id: str
    source_row_sha256: str
    transform_name: str
    transform_version: str
    event_time: datetime
    available_at: datetime
    ingested_at: datetime
    quality_status: str
    quality_report_id: str
    business_fields: tuple[tuple[str, Scalar], ...]


@dataclass(frozen=True, slots=True)
class CanonicalBatch:
    """Content-addressed canonical artifact and its field-level lineage."""

    artifact_id: str
    source_snapshot_id: str
    schema_manifest_id: str
    transform_name: str
    transform_version: str
    quality_status: str
    collection: str
    records: tuple[CanonicalRecord, ...]
    field_mappings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RecordContext:
    batch: SnapshotBatch
    schema: EndpointSchema
    schema_manifest_id: str
    quality_status: str
    quality_report_id: str


def canonicalize_batch(
    batch: SnapshotBatch,
    schema: EndpointSchema,
    schema_manifest_id: str,
) -> CanonicalBatch:
    """Apply the registered PIT policy without mutating provider values."""
    quality_status = "QUARANTINED" if batch.snapshot.endpoint in _PIT_SPLIT_REQUIRED else "ACCEPTED"
    quality_digest = hashlib.sha256(
        f"{batch.snapshot.snapshot_id}|{_TRANSFORM_VERSION}".encode()
    ).hexdigest()
    quality_report_id = f"quality_canonical_{quality_digest}"
    context = _RecordContext(
        batch=batch,
        schema=schema,
        schema_manifest_id=schema_manifest_id,
        quality_status=quality_status,
        quality_report_id=quality_report_id,
    )
    records = tuple(_canonical_record(context, row_index) for row_index in range(len(batch.rows)))
    identity = "|".join(record.record_id for record in records)
    artifact_digest = hashlib.sha256(
        (
            f"{batch.snapshot.snapshot_id}|{schema_manifest_id}|{_TRANSFORM_VERSION}|{identity}"
        ).encode()
    ).hexdigest()
    mappings = tuple(
        f"{schema.canonical_collection}.{field[0]}<-{schema.raw_collection}.payload.{field[0]}"
        for field in schema.fields
    )
    return CanonicalBatch(
        artifact_id=f"canonical_{artifact_digest}",
        source_snapshot_id=batch.snapshot.snapshot_id,
        schema_manifest_id=schema_manifest_id,
        transform_name=_TRANSFORM_NAME,
        transform_version=_TRANSFORM_VERSION,
        quality_status=quality_status,
        collection=schema.canonical_collection,
        records=records,
        field_mappings=mappings,
    )


def _canonical_record(
    context: _RecordContext,
    row_index: int,
) -> CanonicalRecord:
    row = context.batch.rows[row_index]
    payload = dict(row.payload)
    event_time, available_at = _resolve_times(
        context.schema,
        payload,
        context.batch.snapshot.completed_at,
    )
    digest = hashlib.sha256(
        f"{row.row_sha256}|{context.schema_manifest_id}|{_TRANSFORM_VERSION}".encode()
    ).hexdigest()
    return CanonicalRecord(
        record_id=f"record_{digest}",
        schema_manifest_id=context.schema_manifest_id,
        source_snapshot_id=context.batch.snapshot.snapshot_id,
        source_row_sha256=row.row_sha256,
        transform_name=_TRANSFORM_NAME,
        transform_version=_TRANSFORM_VERSION,
        event_time=event_time,
        available_at=available_at,
        ingested_at=context.batch.snapshot.completed_at,
        quality_status=context.quality_status,
        quality_report_id=context.quality_report_id,
        business_fields=row.payload,
    )


def _resolve_times(
    schema: EndpointSchema,
    payload: dict[str, Scalar],
    observed_at: datetime,
) -> tuple[datetime, datetime]:
    if schema.available_at_policy in {
        "observed_master_snapshot",
        "observed_membership_snapshot",
    }:
        return observed_at, observed_at
    raw_date = payload.get(schema.event_time_field)
    if not isinstance(raw_date, str):
        detail = f"event time field is missing or invalid: {schema.event_time_field}"
        raise SchemaContractError(detail)
    event_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
    match schema.available_at_policy:
        case "trade_date_close_plus_provider_delay":
            event_at = datetime.combine(event_date, time(15, 0), _SHANGHAI)
            available_at = datetime.combine(event_date, time(16, 0), _SHANGHAI)
        case "known_before_trade_date_open":
            event_at = datetime.combine(event_date, time(0, 0), _SHANGHAI)
            available_at = datetime.combine(event_date, time(9, 25), _SHANGHAI)
        case "observed_calendar_snapshot" | "source_snapshot_observed_at":
            event_at = datetime.combine(event_date, time(0, 0), _SHANGHAI)
            available_at = observed_at
        case "announcement_date_or_observed":
            event_at = datetime.combine(event_date, time(0, 0), _SHANGHAI)
            raw_announcement = payload.get("ann_date")
            if isinstance(raw_announcement, str):
                announcement = date(
                    int(raw_announcement[:4]),
                    int(raw_announcement[4:6]),
                    int(raw_announcement[6:8]),
                )
                announced_at = datetime.combine(announcement, time(18, 0), _SHANGHAI)
                available_at = min(announced_at, observed_at)
            else:
                available_at = observed_at
        case "financial_actual_announcement_or_observed":
            event_at = datetime.combine(event_date, time(0, 0), _SHANGHAI)
            raw_announcement = payload.get("f_ann_date") or payload.get("ann_date")
            if isinstance(raw_announcement, str):
                announcement = date(
                    int(raw_announcement[:4]),
                    int(raw_announcement[4:6]),
                    int(raw_announcement[6:8]),
                )
                announced_at = datetime.combine(announcement, time(18, 0), _SHANGHAI)
                available_at = min(announced_at, observed_at)
            else:
                available_at = observed_at
        case _:
            detail = f"unsupported available_at policy: {schema.available_at_policy}"
            raise SchemaContractError(detail)
    return event_at, available_at
