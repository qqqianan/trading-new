"""Closed Mongo documents and field lineage for income PIT versions."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.financials import IncomeVersion

_FINANCIAL_FIELDS: Final[tuple[str, ...]] = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "basic_eps",
    "diluted_eps",
    "total_revenue",
    "revenue",
    "operate_profit",
    "total_profit",
    "income_tax",
    "n_income",
    "n_income_attr_p",
    "ebit",
    "ebitda",
    "rd_exp",
    "update_flag",
)


def income_version_document(event: IncomeVersion) -> BsonDocument:
    """Serialize one version under the closed income PIT schema."""
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
        "basic_eps": event.basic_eps,
        "diluted_eps": event.diluted_eps,
        "total_revenue": event.total_revenue,
        "revenue": event.revenue,
        "operate_profit": event.operate_profit,
        "total_profit": event.total_profit,
        "income_tax": event.income_tax,
        "n_income": event.n_income,
        "n_income_attr_p": event.n_income_attr_p,
        "ebit": event.ebit,
        "ebitda": event.ebitda,
        "rd_exp": event.rd_exp,
        "update_flag": event.update_flag,
    }


def income_version_lineage(event: IncomeVersion, code_commit: str) -> BsonDocument:
    """Map all income values and the publication clock to source fields."""
    lineage_id = income_version_lineage_id(event)
    raw = f"raw_tushare_{event.source_endpoint}.payload"
    mappings = tuple(f"pit_income_statements.{field}<-{raw}.{field}" for field in _FINANCIAL_FIELDS)
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
            *mappings,
            f"pit_income_statements.effective_at<-{raw}.f_ann_date|ann_date",
        ],
        "executed_at": event.ingested_at,
    }


def income_version_lineage_id(event: IncomeVersion) -> str:
    """Return the stable event-lineage edge identity."""
    return f"lineage_{hashlib.sha256(f'{event.event_id}|lineage'.encode()).hexdigest()}"
