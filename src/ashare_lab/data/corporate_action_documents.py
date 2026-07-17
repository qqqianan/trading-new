"""Closed documents, quality, and field lineage for dividend PIT events."""

import hashlib

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.corporate_actions import DividendEvent, DividendEventType


def dividend_event_document(event: DividendEvent) -> BsonDocument:
    """Serialize one stage-safe event under the closed managed schema."""
    return {
        "_id": event.event_id,
        "event_id": event.event_id,
        "ts_code": event.ts_code,
        "end_date": event.end_date,
        "event_type": event.event_type.value,
        "effective_at": event.effective_at,
        "available_at": event.available_at,
        "ingested_at": event.ingested_at,
        "div_proc": event.div_proc,
        "stk_div": event.stk_div,
        "stk_bo_rate": event.stk_bo_rate,
        "stk_co_rate": event.stk_co_rate,
        "cash_div": event.cash_div,
        "cash_div_tax": event.cash_div_tax,
        "record_date": event.record_date,
        "ex_date": event.ex_date,
        "pay_date": event.pay_date,
        "div_listdate": event.div_listdate,
        "source_snapshot_id": event.source_snapshot_id,
        "source_row_sha256": event.source_row_sha256,
        "input_schema_manifest_id": event.input_schema_manifest_id,
        "schema_manifest_id": event.schema_manifest_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "quality_status": event.quality_status,
        "quality_report_id": event.quality_report_id,
    }


def dividend_lineage_document(event: DividendEvent, code_commit: str) -> BsonDocument:
    """Map every exposed stage field to an exact Tushare dividend column."""
    lineage_id = dividend_event_lineage_id(event)
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
        "parameters_sha256": hashlib.sha256(event.event_type.value.encode()).hexdigest(),
        "field_mappings": list(_field_mappings(event.event_type)),
        "executed_at": event.ingested_at,
    }


def dividend_event_quality_document(event: DividendEvent) -> BsonDocument:
    """Create the immutable quality decision for one accepted PIT event."""
    return {
        "_id": event.quality_report_id,
        "quality_report_id": event.quality_report_id,
        "artifact_id": event.event_id,
        "rulebook_version": "1.1.0",
        "checks": ["stage_field_isolation", "point_in_time_availability", "field_lineage"],
        "passed": True,
        "failure_codes": [],
        "checked_at": event.ingested_at,
    }


def dividend_event_lineage_id(event: DividendEvent) -> str:
    """Return one stable event-level lineage identity."""
    digest = hashlib.sha256(f"{event.event_id}|lineage".encode()).hexdigest()
    return f"lineage_{digest}"


def _field_mappings(event_type: DividendEventType) -> tuple[str, ...]:
    raw = "raw_tushare_dividend.payload"
    common = tuple(
        f"pit_dividend_events.{field}<-{raw}.{field}"
        for field in (
            "ts_code",
            "end_date",
            "div_proc",
            "stk_div",
            "stk_bo_rate",
            "stk_co_rate",
            "cash_div",
            "cash_div_tax",
        )
    )
    match event_type:
        case DividendEventType.PLAN_ANNOUNCED:
            return (*common, f"pit_dividend_events.effective_at<-{raw}.ann_date")
        case DividendEventType.IMPLEMENTATION_ANNOUNCED:
            implementation = tuple(
                f"pit_dividend_events.{field}<-{raw}.{field}"
                for field in ("record_date", "ex_date", "pay_date", "div_listdate")
            )
            return (
                *common,
                f"pit_dividend_events.effective_at<-{raw}.imp_ann_date",
                *implementation,
            )
