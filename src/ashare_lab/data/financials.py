"""Point-in-time financial statement version events."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique

from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.tushare_client import Scalar

_TRANSFORM_NAME = "income_row_to_pit_version"
_TRANSFORM_VERSION = "1.0.0"


@unique
class FinancialEventType(StrEnum):
    """Closed financial lifecycle transitions."""

    VERSION_PUBLISHED = "FINANCIAL_VERSION_PUBLISHED"


@dataclass(frozen=True, slots=True)
class IncomeVersion:
    """One immutable, publication-timed income statement version."""

    event_id: str
    event_type: FinancialEventType
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    source_endpoint: str
    source_snapshot_id: str
    source_row_sha256: str
    input_schema_manifest_id: str
    schema_manifest_id: str
    transform_name: str
    transform_version: str
    quality_status: str
    quality_report_id: str
    ts_code: str
    ann_date: str | None
    f_ann_date: str | None
    end_date: str
    report_type: str | None
    comp_type: str | None
    end_type: str | None
    basic_eps: float | None
    diluted_eps: float | None
    total_revenue: float | None
    revenue: float | None
    operate_profit: float | None
    total_profit: float | None
    income_tax: float | None
    n_income: float | None
    n_income_attr_p: float | None
    ebit: float | None
    ebitda: float | None
    rd_exp: float | None
    update_flag: str | None


def build_income_version(record: CanonicalRecord, source_endpoint: str) -> IncomeVersion:
    """Project one quarantined source row into a publication-timed PIT version."""
    if source_endpoint not in {"income", "income_vip"}:
        detail = f"unsupported income source endpoint: {source_endpoint}"
        raise SchemaContractError(detail)
    payload = dict(record.business_fields)
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|"
        f"{record.schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    event_id = f"income_event_{hashlib.sha256(identity.encode()).hexdigest()}"
    quality_id = f"quality_{hashlib.sha256(event_id.encode()).hexdigest()}"
    return IncomeVersion(
        event_id=event_id,
        event_type=FinancialEventType.VERSION_PUBLISHED,
        effective_at=record.available_at,
        available_at=record.available_at,
        ingested_at=record.ingested_at,
        source_endpoint=source_endpoint,
        source_snapshot_id=record.source_snapshot_id,
        source_row_sha256=record.source_row_sha256,
        input_schema_manifest_id=record.schema_manifest_id,
        schema_manifest_id=record.schema_manifest_id,
        transform_name=_TRANSFORM_NAME,
        transform_version=_TRANSFORM_VERSION,
        quality_status="ACCEPTED",
        quality_report_id=quality_id,
        ts_code=_required_string(payload, "ts_code"),
        ann_date=_optional_string(payload, "ann_date"),
        f_ann_date=_optional_string(payload, "f_ann_date"),
        end_date=_required_string(payload, "end_date"),
        report_type=_optional_string(payload, "report_type"),
        comp_type=_optional_string(payload, "comp_type"),
        end_type=_optional_string(payload, "end_type"),
        basic_eps=_optional_float(payload, "basic_eps"),
        diluted_eps=_optional_float(payload, "diluted_eps"),
        total_revenue=_optional_float(payload, "total_revenue"),
        revenue=_optional_float(payload, "revenue"),
        operate_profit=_optional_float(payload, "operate_profit"),
        total_profit=_optional_float(payload, "total_profit"),
        income_tax=_optional_float(payload, "income_tax"),
        n_income=_optional_float(payload, "n_income"),
        n_income_attr_p=_optional_float(payload, "n_income_attr_p"),
        ebit=_optional_float(payload, "ebit"),
        ebitda=_optional_float(payload, "ebitda"),
        rd_exp=_optional_float(payload, "rd_exp"),
        update_flag=_optional_string(payload, "update_flag"),
    )


def select_income_versions(
    events: tuple[IncomeVersion, ...],
    decision_time: datetime,
) -> tuple[IncomeVersion, ...]:
    """Return only accepted versions published by one aware decision time."""
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


def _required_string(payload: dict[str, Scalar], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    detail = f"income source field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _optional_string(payload: dict[str, Scalar], field: str) -> str | None:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    if value is None:
        return None
    detail = f"income source field is invalid: {field}"
    raise SchemaContractError(detail)


def _optional_float(payload: dict[str, Scalar], field: str) -> float | None:
    value = payload.get(field)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    detail = f"income source field is invalid: {field}"
    raise SchemaContractError(detail)
