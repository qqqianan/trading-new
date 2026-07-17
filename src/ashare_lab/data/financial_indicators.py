"""Point-in-time financial-indicator version events."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.financials import FinancialEventType
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.tushare_client import Scalar

_TRANSFORM_NAME = "financial_indicator_row_to_pit_version"
_TRANSFORM_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class FinancialIndicatorVersion:
    """One immutable, publication-timed financial-indicator version."""

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
    end_date: str
    eps: float | None
    dt_eps: float | None
    total_revenue_ps: float | None
    revenue_ps: float | None
    bps: float | None
    ocfps: float | None
    gross_margin: float | None
    netprofit_margin: float | None
    grossprofit_margin: float | None
    roe: float | None
    roe_waa: float | None
    roe_dt: float | None
    roa: float | None
    roic: float | None
    current_ratio: float | None
    quick_ratio: float | None
    cash_ratio: float | None
    debt_to_assets: float | None
    assets_to_eqt: float | None
    inv_turn: float | None
    ar_turn: float | None
    assets_turn: float | None
    ocf_to_debt: float | None
    ebit_to_interest: float | None
    fcff: float | None
    fcfe: float | None
    q_sales_yoy: float | None
    q_op_yoy: float | None
    q_profit_yoy: float | None
    q_netprofit_yoy: float | None
    basic_eps_yoy: float | None
    dt_eps_yoy: float | None
    netprofit_yoy: float | None
    tr_yoy: float | None
    or_yoy: float | None
    update_flag: str | None


def build_financial_indicator_version(record: CanonicalRecord) -> FinancialIndicatorVersion:
    """Project one quarantined indicator row into an accepted PIT version."""
    payload = dict(record.business_fields)
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|"
        f"{record.schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    event_id = f"financial_indicator_event_{hashlib.sha256(identity.encode()).hexdigest()}"
    quality_id = f"quality_{hashlib.sha256(event_id.encode()).hexdigest()}"
    return FinancialIndicatorVersion(
        event_id=event_id,
        event_type=FinancialEventType.VERSION_PUBLISHED,
        effective_at=record.available_at,
        available_at=record.available_at,
        ingested_at=record.ingested_at,
        source_endpoint="fina_indicator",
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
        end_date=_required_string(payload, "end_date"),
        eps=_optional_float(payload, "eps"),
        dt_eps=_optional_float(payload, "dt_eps"),
        total_revenue_ps=_optional_float(payload, "total_revenue_ps"),
        revenue_ps=_optional_float(payload, "revenue_ps"),
        bps=_optional_float(payload, "bps"),
        ocfps=_optional_float(payload, "ocfps"),
        gross_margin=_optional_float(payload, "gross_margin"),
        netprofit_margin=_optional_float(payload, "netprofit_margin"),
        grossprofit_margin=_optional_float(payload, "grossprofit_margin"),
        roe=_optional_float(payload, "roe"),
        roe_waa=_optional_float(payload, "roe_waa"),
        roe_dt=_optional_float(payload, "roe_dt"),
        roa=_optional_float(payload, "roa"),
        roic=_optional_float(payload, "roic"),
        current_ratio=_optional_float(payload, "current_ratio"),
        quick_ratio=_optional_float(payload, "quick_ratio"),
        cash_ratio=_optional_float(payload, "cash_ratio"),
        debt_to_assets=_optional_float(payload, "debt_to_assets"),
        assets_to_eqt=_optional_float(payload, "assets_to_eqt"),
        inv_turn=_optional_float(payload, "inv_turn"),
        ar_turn=_optional_float(payload, "ar_turn"),
        assets_turn=_optional_float(payload, "assets_turn"),
        ocf_to_debt=_optional_float(payload, "ocf_to_debt"),
        ebit_to_interest=_optional_float(payload, "ebit_to_interest"),
        fcff=_optional_float(payload, "fcff"),
        fcfe=_optional_float(payload, "fcfe"),
        q_sales_yoy=_optional_float(payload, "q_sales_yoy"),
        q_op_yoy=_optional_float(payload, "q_op_yoy"),
        q_profit_yoy=_optional_float(payload, "q_profit_yoy"),
        q_netprofit_yoy=_optional_float(payload, "q_netprofit_yoy"),
        basic_eps_yoy=_optional_float(payload, "basic_eps_yoy"),
        dt_eps_yoy=_optional_float(payload, "dt_eps_yoy"),
        netprofit_yoy=_optional_float(payload, "netprofit_yoy"),
        tr_yoy=_optional_float(payload, "tr_yoy"),
        or_yoy=_optional_float(payload, "or_yoy"),
        update_flag=_optional_string(payload, "update_flag"),
    )


METRIC_FIELDS = (
    "eps",
    "dt_eps",
    "total_revenue_ps",
    "revenue_ps",
    "bps",
    "ocfps",
    "gross_margin",
    "netprofit_margin",
    "grossprofit_margin",
    "roe",
    "roe_waa",
    "roe_dt",
    "roa",
    "roic",
    "current_ratio",
    "quick_ratio",
    "cash_ratio",
    "debt_to_assets",
    "assets_to_eqt",
    "inv_turn",
    "ar_turn",
    "assets_turn",
    "ocf_to_debt",
    "ebit_to_interest",
    "fcff",
    "fcfe",
    "q_sales_yoy",
    "q_op_yoy",
    "q_profit_yoy",
    "q_netprofit_yoy",
    "basic_eps_yoy",
    "dt_eps_yoy",
    "netprofit_yoy",
    "tr_yoy",
    "or_yoy",
)


def _required_string(payload: dict[str, Scalar], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    detail = f"financial-indicator source field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _optional_string(payload: dict[str, Scalar], field: str) -> str | None:
    value = payload.get(field)
    if isinstance(value, str) or value is None:
        return value
    detail = f"financial-indicator source field is invalid: {field}"
    raise SchemaContractError(detail)


def _optional_float(payload: dict[str, Scalar], field: str) -> float | None:
    value = payload.get(field)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    detail = f"financial-indicator source field is invalid: {field}"
    raise SchemaContractError(detail)
