"""Observed-at industry membership intervals projected from quarantined rows."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ashare_lab.data.canonical import CanonicalBatch, CanonicalRecord
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.tushare_client import Scalar

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRANSFORM_NAME = "industry_member_row_to_observed_pit_interval"
_TRANSFORM_VERSION = "1.0.0"
_PROVIDER_ROW_CAP = 5_000


@dataclass(frozen=True, slots=True)
class IndustryMembership:
    """One historical interval whose knowledge begins at observation time."""

    membership_id: str
    available_at: datetime
    ingested_at: datetime
    effective_from: datetime
    effective_to: datetime | None
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
    in_date: str
    out_date: str | None
    is_new: str | None


def validate_industry_membership_batch(batch: CanonicalBatch) -> None:
    """Reject mixed-industry or provider-capped membership responses."""
    if not batch.records:
        return
    events = tuple(build_industry_membership(record) for record in batch.records)
    if len({event.index_code for event in events}) != 1:
        detail = "industry membership batch contains multiple industry codes"
        raise SchemaContractError(detail)
    if len(events) >= _PROVIDER_ROW_CAP:
        detail = "industry membership response reached provider row cap"
        raise SchemaContractError(detail)


def build_industry_membership(record: CanonicalRecord) -> IndustryMembership:
    """Project one observed provider interval into an accepted PIT fact."""
    payload = dict(record.business_fields)
    index_code = _required_string(payload, "index_code")
    con_code = _required_string(payload, "con_code")
    in_date = _required_string(payload, "in_date")
    out_value = payload.get("out_date")
    out_date = out_value if isinstance(out_value, str) else None
    effective_from = _midnight(in_date)
    effective_to = _midnight(out_date) if out_date is not None else None
    if effective_to is not None and effective_to < effective_from:
        detail = "industry membership ends before it begins"
        raise SchemaContractError(detail)
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|"
        f"{record.schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    membership_id = f"industry_membership_{hashlib.sha256(identity.encode()).hexdigest()}"
    is_new_value = payload.get("is_new")
    return IndustryMembership(
        membership_id=membership_id,
        available_at=record.available_at,
        ingested_at=record.ingested_at,
        effective_from=effective_from,
        effective_to=effective_to,
        source_snapshot_id=record.source_snapshot_id,
        source_row_sha256=record.source_row_sha256,
        input_schema_manifest_id=record.schema_manifest_id,
        schema_manifest_id=record.schema_manifest_id,
        transform_name=_TRANSFORM_NAME,
        transform_version=_TRANSFORM_VERSION,
        quality_status="ACCEPTED",
        quality_report_id=f"quality_{hashlib.sha256(membership_id.encode()).hexdigest()}",
        index_code=index_code,
        con_code=con_code,
        in_date=in_date,
        out_date=out_date,
        is_new=is_new_value if isinstance(is_new_value, str) else None,
    )


def _required_string(payload: dict[str, Scalar], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str) and value != "":
        return value
    detail = f"industry membership field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _midnight(raw_date: str) -> datetime:
    parsed = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
    return datetime.combine(parsed, time(0, 0), _SHANGHAI)
