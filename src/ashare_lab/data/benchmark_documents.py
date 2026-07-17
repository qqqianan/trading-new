"""Closed Mongo documents and lineage for index-weight PIT events."""

import hashlib

from ashare_lab.data.benchmark_weights import IndexWeightEvent
from ashare_lab.data.bson_types import BsonDocument


def index_weight_document(event: IndexWeightEvent) -> BsonDocument:
    """Serialize one index-weight event under the closed PIT contract."""
    return {
        "_id": event.event_id,
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "effective_at": event.effective_at,
        "available_at": event.available_at,
        "ingested_at": event.ingested_at,
        "source_snapshot_id": event.source_snapshot_id,
        "source_row_sha256": event.source_row_sha256,
        "input_schema_manifest_id": event.input_schema_manifest_id,
        "schema_manifest_id": event.schema_manifest_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "quality_status": event.quality_status,
        "quality_report_id": event.quality_report_id,
        "index_code": event.index_code,
        "con_code": event.con_code,
        "trade_date": event.trade_date,
        "weight": event.weight,
    }


def index_weight_lineage(event: IndexWeightEvent, code_commit: str) -> BsonDocument:
    """Map index identity, constituent, date, weight, and clock to Raw fields."""
    lineage_id = index_weight_lineage_id(event)
    raw = "raw_tushare_index_weight.payload"
    fields = ("index_code", "con_code", "trade_date", "weight")
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
        "parameters_sha256": hashlib.sha256(b"weight_date_close_clock").hexdigest(),
        "field_mappings": [
            *(f"pit_index_weights.{field}<-{raw}.{field}" for field in fields),
            f"pit_index_weights.effective_at<-{raw}.trade_date",
        ],
        "executed_at": event.ingested_at,
    }


def index_weight_lineage_id(event: IndexWeightEvent) -> str:
    """Return one stable event-lineage edge identity."""
    return f"lineage_{hashlib.sha256(f'{event.event_id}|lineage'.encode()).hexdigest()}"
