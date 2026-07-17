"""Point-in-time balance-sheet version events."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.financials import FinancialEventType
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.tushare_client import Scalar

_TRANSFORM_NAME = "balance_sheet_row_to_pit_version"
_TRANSFORM_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class BalanceSheetVersion:
    """One immutable, publication-timed balance-sheet version."""

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
    total_share: float | None
    cap_rese: float | None
    undistr_porfit: float | None
    surplus_rese: float | None
    money_cap: float | None
    accounts_receiv: float | None
    inventories: float | None
    total_cur_assets: float | None
    fix_assets: float | None
    goodwill: float | None
    total_assets: float | None
    st_borr: float | None
    lt_borr: float | None
    total_cur_liab: float | None
    total_ncl: float | None
    total_liab: float | None
    total_hldr_eqy_exc_min_int: float | None
    total_hldr_eqy_inc_min_int: float | None
    total_liab_hldr_eqy: float | None
    update_flag: str | None


def build_balance_sheet_version(record: CanonicalRecord) -> BalanceSheetVersion:
    """Project one quarantined balance sheet into an accepted PIT version."""
    payload = dict(record.business_fields)
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|"
        f"{record.schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    event_id = f"balance_sheet_event_{hashlib.sha256(identity.encode()).hexdigest()}"
    quality_id = f"quality_{hashlib.sha256(event_id.encode()).hexdigest()}"
    return BalanceSheetVersion(
        event_id=event_id,
        event_type=FinancialEventType.VERSION_PUBLISHED,
        effective_at=record.available_at,
        available_at=record.available_at,
        ingested_at=record.ingested_at,
        source_endpoint="balancesheet",
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
        total_share=_optional_float(payload, "total_share"),
        cap_rese=_optional_float(payload, "cap_rese"),
        undistr_porfit=_optional_float(payload, "undistr_porfit"),
        surplus_rese=_optional_float(payload, "surplus_rese"),
        money_cap=_optional_float(payload, "money_cap"),
        accounts_receiv=_optional_float(payload, "accounts_receiv"),
        inventories=_optional_float(payload, "inventories"),
        total_cur_assets=_optional_float(payload, "total_cur_assets"),
        fix_assets=_optional_float(payload, "fix_assets"),
        goodwill=_optional_float(payload, "goodwill"),
        total_assets=_optional_float(payload, "total_assets"),
        st_borr=_optional_float(payload, "st_borr"),
        lt_borr=_optional_float(payload, "lt_borr"),
        total_cur_liab=_optional_float(payload, "total_cur_liab"),
        total_ncl=_optional_float(payload, "total_ncl"),
        total_liab=_optional_float(payload, "total_liab"),
        total_hldr_eqy_exc_min_int=_optional_float(payload, "total_hldr_eqy_exc_min_int"),
        total_hldr_eqy_inc_min_int=_optional_float(payload, "total_hldr_eqy_inc_min_int"),
        total_liab_hldr_eqy=_optional_float(payload, "total_liab_hldr_eqy"),
        update_flag=_optional_string(payload, "update_flag"),
    )


def _required_string(payload: dict[str, Scalar], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    detail = f"balance-sheet source field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _optional_string(payload: dict[str, Scalar], field: str) -> str | None:
    value = payload.get(field)
    if isinstance(value, str) or value is None:
        return value
    detail = f"balance-sheet source field is invalid: {field}"
    raise SchemaContractError(detail)


def _optional_float(payload: dict[str, Scalar], field: str) -> float | None:
    value = payload.get(field)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    detail = f"balance-sheet source field is invalid: {field}"
    raise SchemaContractError(detail)
