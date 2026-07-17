"""Closed documents and field lineage for cash-flow PIT versions."""

import hashlib
from typing import Final

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.cashflows import CashflowVersion

_FIELDS: Final[tuple[str, ...]] = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "net_profit",
    "finan_exp",
    "c_fr_sale_sg",
    "recp_tax_rends",
    "c_fr_oth_operate_a",
    "c_inf_fr_operate_a",
    "c_paid_goods_s",
    "c_paid_to_for_empl",
    "c_paid_for_taxes",
    "oth_cash_pay_oper_act",
    "st_cash_out_act",
    "n_cashflow_act",
    "c_disp_withdrwl_invest",
    "c_recp_return_invest",
    "c_pay_acq_const_fiolta",
    "c_paid_invest",
    "n_cashflow_inv_act",
    "c_recp_borrow",
    "proc_issue_bonds",
    "c_prepay_amt_borr",
    "c_pay_dist_dpcp_int_exp",
    "n_cash_flows_fnc_act",
    "n_incr_cash_cash_equ",
    "c_cash_equ_beg_period",
    "c_cash_equ_end_period",
    "free_cashflow",
    "update_flag",
)


def cashflow_document(event: CashflowVersion) -> BsonDocument:
    """Serialize one event under the closed cash-flow PIT contract."""
    return {
        "_id": event.event_id,
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "effective_at": event.effective_at,
        "available_at": event.available_at,
        "ingested_at": event.ingested_at,
        "source_endpoint": event.source_endpoint,
        "source_snapshot_id": event.source_snapshot_id,
        "source_row_sha256": event.source_row_sha256,
        "input_schema_manifest_id": event.input_schema_manifest_id,
        "schema_manifest_id": event.schema_manifest_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "quality_status": event.quality_status,
        "quality_report_id": event.quality_report_id,
        "ts_code": event.ts_code,
        "ann_date": event.ann_date,
        "f_ann_date": event.f_ann_date,
        "end_date": event.end_date,
        "report_type": event.report_type,
        "comp_type": event.comp_type,
        "end_type": event.end_type,
        "net_profit": event.net_profit,
        "finan_exp": event.finan_exp,
        "c_fr_sale_sg": event.c_fr_sale_sg,
        "recp_tax_rends": event.recp_tax_rends,
        "c_fr_oth_operate_a": event.c_fr_oth_operate_a,
        "c_inf_fr_operate_a": event.c_inf_fr_operate_a,
        "c_paid_goods_s": event.c_paid_goods_s,
        "c_paid_to_for_empl": event.c_paid_to_for_empl,
        "c_paid_for_taxes": event.c_paid_for_taxes,
        "oth_cash_pay_oper_act": event.oth_cash_pay_oper_act,
        "st_cash_out_act": event.st_cash_out_act,
        "n_cashflow_act": event.n_cashflow_act,
        "c_disp_withdrwl_invest": event.c_disp_withdrwl_invest,
        "c_recp_return_invest": event.c_recp_return_invest,
        "c_pay_acq_const_fiolta": event.c_pay_acq_const_fiolta,
        "c_paid_invest": event.c_paid_invest,
        "n_cashflow_inv_act": event.n_cashflow_inv_act,
        "c_recp_borrow": event.c_recp_borrow,
        "proc_issue_bonds": event.proc_issue_bonds,
        "c_prepay_amt_borr": event.c_prepay_amt_borr,
        "c_pay_dist_dpcp_int_exp": event.c_pay_dist_dpcp_int_exp,
        "n_cash_flows_fnc_act": event.n_cash_flows_fnc_act,
        "n_incr_cash_cash_equ": event.n_incr_cash_cash_equ,
        "c_cash_equ_beg_period": event.c_cash_equ_beg_period,
        "c_cash_equ_end_period": event.c_cash_equ_end_period,
        "free_cashflow": event.free_cashflow,
        "update_flag": event.update_flag,
    }


def cashflow_lineage(event: CashflowVersion, code_commit: str) -> BsonDocument:
    """Map every PIT field and publication clock to its immutable Raw row."""
    lineage_id = cashflow_lineage_id(event)
    raw = "raw_tushare_cashflow.payload"
    return {
        "_id": lineage_id,
        "lineage_edge_id": lineage_id,
        "upstream_artifact_id": event.source_snapshot_id,
        "downstream_artifact_id": event.event_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "code_commit": code_commit,
        "input_schema_ids": [event.input_schema_manifest_id],
        "output_schema_id": event.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"actual_announcement_clock").hexdigest(),
        "field_mappings": [
            *(f"pit_cashflow_statements.{field}<-{raw}.{field}" for field in _FIELDS),
            f"pit_cashflow_statements.effective_at<-{raw}.f_ann_date|ann_date",
        ],
        "executed_at": event.ingested_at,
    }


def cashflow_lineage_id(event: CashflowVersion) -> str:
    """Return the stable lineage edge identity for one PIT event."""
    return f"lineage_{hashlib.sha256(f'{event.event_id}|lineage'.encode()).hexdigest()}"
