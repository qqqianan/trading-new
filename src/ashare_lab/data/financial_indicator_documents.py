"""Closed documents and lineage for financial-indicator PIT versions."""

import hashlib

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.financial_indicators import METRIC_FIELDS, FinancialIndicatorVersion


def financial_indicator_document(event: FinancialIndicatorVersion) -> BsonDocument:
    """Serialize one event under the closed indicator PIT contract."""
    metrics = {
        "eps": event.eps,
        "dt_eps": event.dt_eps,
        "total_revenue_ps": event.total_revenue_ps,
        "revenue_ps": event.revenue_ps,
        "bps": event.bps,
        "ocfps": event.ocfps,
        "gross_margin": event.gross_margin,
        "netprofit_margin": event.netprofit_margin,
        "grossprofit_margin": event.grossprofit_margin,
        "roe": event.roe,
        "roe_waa": event.roe_waa,
        "roe_dt": event.roe_dt,
        "roa": event.roa,
        "roic": event.roic,
        "current_ratio": event.current_ratio,
        "quick_ratio": event.quick_ratio,
        "cash_ratio": event.cash_ratio,
        "debt_to_assets": event.debt_to_assets,
        "assets_to_eqt": event.assets_to_eqt,
        "inv_turn": event.inv_turn,
        "ar_turn": event.ar_turn,
        "assets_turn": event.assets_turn,
        "ocf_to_debt": event.ocf_to_debt,
        "ebit_to_interest": event.ebit_to_interest,
        "fcff": event.fcff,
        "fcfe": event.fcfe,
        "q_sales_yoy": event.q_sales_yoy,
        "q_op_yoy": event.q_op_yoy,
        "q_profit_yoy": event.q_profit_yoy,
        "q_netprofit_yoy": event.q_netprofit_yoy,
        "basic_eps_yoy": event.basic_eps_yoy,
        "dt_eps_yoy": event.dt_eps_yoy,
        "netprofit_yoy": event.netprofit_yoy,
        "tr_yoy": event.tr_yoy,
        "or_yoy": event.or_yoy,
    }
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
        "end_date": event.end_date,
        **metrics,
        "update_flag": event.update_flag,
    }


def financial_indicator_lineage(event: FinancialIndicatorVersion) -> BsonDocument:
    """Map every PIT field and announcement clock to the immutable Raw row."""
    lineage_id = financial_indicator_lineage_id(event)
    raw = "raw_tushare_fina_indicator.payload"
    fields = ("ts_code", "ann_date", "end_date", *METRIC_FIELDS, "update_flag")
    return {
        "_id": lineage_id,
        "lineage_edge_id": lineage_id,
        "upstream_artifact_id": event.source_snapshot_id,
        "downstream_artifact_id": event.event_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "code_commit": "workspace_unversioned",
        "input_schema_ids": [event.input_schema_manifest_id],
        "output_schema_id": event.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"announcement_clock").hexdigest(),
        "field_mappings": [
            *(f"pit_financial_indicators.{f}<-{raw}.{f}" for f in fields),
            f"pit_financial_indicators.effective_at<-{raw}.ann_date",
        ],
        "executed_at": event.ingested_at,
    }


def financial_indicator_lineage_id(event: FinancialIndicatorVersion) -> str:
    """Return one stable event-lineage identity."""
    return f"lineage_{hashlib.sha256(f'{event.event_id}|lineage'.encode()).hexdigest()}"
