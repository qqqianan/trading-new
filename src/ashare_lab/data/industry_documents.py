"""Closed Mongo documents and field lineage for industry memberships."""

import hashlib

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.industry_memberships import IndustryMembership


def industry_membership_document(event: IndustryMembership) -> BsonDocument:
    """Serialize one accepted observed-at industry interval."""
    return {
        "_id": event.membership_id,
        "membership_id": event.membership_id,
        "available_at": event.available_at,
        "ingested_at": event.ingested_at,
        "effective_from": event.effective_from,
        "effective_to": event.effective_to,
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
        "in_date": event.in_date,
        "out_date": event.out_date,
        "is_new": event.is_new,
    }


def industry_membership_lineage(event: IndustryMembership, code_commit: str) -> BsonDocument:
    """Map identity, interval, and knowledge clock to one Raw row."""
    lineage_id = industry_membership_lineage_id(event)
    raw = "raw_tushare_index_member.payload"
    return {
        "_id": lineage_id,
        "lineage_edge_id": lineage_id,
        "upstream_artifact_id": event.source_snapshot_id,
        "downstream_artifact_id": event.membership_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "code_commit": code_commit,
        "input_schema_ids": [event.input_schema_manifest_id],
        "output_schema_id": event.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"observed_membership_clock").hexdigest(),
        "field_mappings": [
            *(
                f"pit_industry_memberships.{field}<-{raw}.{field}"
                for field in ("index_code", "con_code", "in_date", "out_date", "is_new")
            ),
            f"pit_industry_memberships.effective_from<-{raw}.in_date",
            f"pit_industry_memberships.effective_to<-{raw}.out_date",
            "pit_industry_memberships.available_at<-meta_source_snapshots.completed_at",
        ],
        "executed_at": event.ingested_at,
    }


def industry_membership_lineage_id(event: IndustryMembership) -> str:
    """Return one stable event-lineage identity."""
    digest = hashlib.sha256(f"{event.membership_id}|lineage".encode()).hexdigest()
    return f"lineage_{digest}"
