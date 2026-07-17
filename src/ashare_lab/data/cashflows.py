"""Point-in-time cash-flow statement version events."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.financials import FinancialEventType
from ashare_lab.data.schema_registry import SchemaContractError
from ashare_lab.data.tushare_client import Scalar

_TRANSFORM_NAME = "cashflow_row_to_pit_version"
_TRANSFORM_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class CashflowVersion:
    """One immutable, publication-timed cash-flow statement version."""

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
    net_profit: float | None
    finan_exp: float | None
    c_fr_sale_sg: float | None
    recp_tax_rends: float | None
    c_fr_oth_operate_a: float | None
    c_inf_fr_operate_a: float | None
    c_paid_goods_s: float | None
    c_paid_to_for_empl: float | None
    c_paid_for_taxes: float | None
    oth_cash_pay_oper_act: float | None
    st_cash_out_act: float | None
    n_cashflow_act: float | None
    c_disp_withdrwl_invest: float | None
    c_recp_return_invest: float | None
    c_pay_acq_const_fiolta: float | None
    c_paid_invest: float | None
    n_cashflow_inv_act: float | None
    c_recp_borrow: float | None
    proc_issue_bonds: float | None
    c_prepay_amt_borr: float | None
    c_pay_dist_dpcp_int_exp: float | None
    n_cash_flows_fnc_act: float | None
    n_incr_cash_cash_equ: float | None
    c_cash_equ_beg_period: float | None
    c_cash_equ_end_period: float | None
    free_cashflow: float | None
    update_flag: str | None


def build_cashflow_version(record: CanonicalRecord) -> CashflowVersion:
    """Project one quarantined cash-flow row into an accepted PIT version."""
    payload = dict(record.business_fields)
    identity = (
        f"{record.source_snapshot_id}|{record.source_row_sha256}|"
        f"{record.schema_manifest_id}|{_TRANSFORM_VERSION}"
    )
    event_id = f"cashflow_event_{hashlib.sha256(identity.encode()).hexdigest()}"
    quality_id = f"quality_{hashlib.sha256(event_id.encode()).hexdigest()}"
    return CashflowVersion(
        event_id=event_id,
        event_type=FinancialEventType.VERSION_PUBLISHED,
        effective_at=record.available_at,
        available_at=record.available_at,
        ingested_at=record.ingested_at,
        source_endpoint="cashflow",
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
        net_profit=_optional_float(payload, "net_profit"),
        finan_exp=_optional_float(payload, "finan_exp"),
        c_fr_sale_sg=_optional_float(payload, "c_fr_sale_sg"),
        recp_tax_rends=_optional_float(payload, "recp_tax_rends"),
        c_fr_oth_operate_a=_optional_float(payload, "c_fr_oth_operate_a"),
        c_inf_fr_operate_a=_optional_float(payload, "c_inf_fr_operate_a"),
        c_paid_goods_s=_optional_float(payload, "c_paid_goods_s"),
        c_paid_to_for_empl=_optional_float(payload, "c_paid_to_for_empl"),
        c_paid_for_taxes=_optional_float(payload, "c_paid_for_taxes"),
        oth_cash_pay_oper_act=_optional_float(payload, "oth_cash_pay_oper_act"),
        st_cash_out_act=_optional_float(payload, "st_cash_out_act"),
        n_cashflow_act=_optional_float(payload, "n_cashflow_act"),
        c_disp_withdrwl_invest=_optional_float(payload, "c_disp_withdrwl_invest"),
        c_recp_return_invest=_optional_float(payload, "c_recp_return_invest"),
        c_pay_acq_const_fiolta=_optional_float(payload, "c_pay_acq_const_fiolta"),
        c_paid_invest=_optional_float(payload, "c_paid_invest"),
        n_cashflow_inv_act=_optional_float(payload, "n_cashflow_inv_act"),
        c_recp_borrow=_optional_float(payload, "c_recp_borrow"),
        proc_issue_bonds=_optional_float(payload, "proc_issue_bonds"),
        c_prepay_amt_borr=_optional_float(payload, "c_prepay_amt_borr"),
        c_pay_dist_dpcp_int_exp=_optional_float(payload, "c_pay_dist_dpcp_int_exp"),
        n_cash_flows_fnc_act=_optional_float(payload, "n_cash_flows_fnc_act"),
        n_incr_cash_cash_equ=_optional_float(payload, "n_incr_cash_cash_equ"),
        c_cash_equ_beg_period=_optional_float(payload, "c_cash_equ_beg_period"),
        c_cash_equ_end_period=_optional_float(payload, "c_cash_equ_end_period"),
        free_cashflow=_optional_float(payload, "free_cashflow"),
        update_flag=_optional_string(payload, "update_flag"),
    )


def _required_string(payload: dict[str, Scalar], field: str) -> str:
    value = payload.get(field)
    if isinstance(value, str):
        return value
    detail = f"cash-flow source field is missing or invalid: {field}"
    raise SchemaContractError(detail)


def _optional_string(payload: dict[str, Scalar], field: str) -> str | None:
    value = payload.get(field)
    if isinstance(value, str) or value is None:
        return value
    detail = f"cash-flow source field is invalid: {field}"
    raise SchemaContractError(detail)


def _optional_float(payload: dict[str, Scalar], field: str) -> float | None:
    value = payload.get(field)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    detail = f"cash-flow source field is invalid: {field}"
    raise SchemaContractError(detail)
