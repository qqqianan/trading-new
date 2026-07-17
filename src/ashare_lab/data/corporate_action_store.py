"""Mongo persistence for dividend PIT events and completion evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pymongo import MongoClient, UpdateOne

from ashare_lab.data.corporate_actions import DividendEvent, DividendEventType

_SHANGHAI = ZoneInfo("Asia/Shanghai")

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch


@dataclass(frozen=True, slots=True)
class DividendWriteResult:
    """Counts and batch identity from one idempotent PIT projection."""

    batch_artifact_id: str
    event_count: int
    inserted_count: int


class MongoDividendEventStore:
    """Append dividend events with event-level and empty-batch evidence."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind the adapter only to the isolated governed database."""
        if database_name != "ashare_quant":
            msg = "dividend event store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write_batch(
        self,
        canonical: CanonicalBatch,
        events: tuple[DividendEvent, ...],
    ) -> DividendWriteResult:
        """Persist a complete projection, including evidence for an empty response."""
        inserted = self._write_events(events)
        artifact_id = dividend_batch_artifact_id(canonical.artifact_id)
        self._database["meta_quality_reports"].update_one(
            {"_id": _batch_quality_id(artifact_id)},
            {"$setOnInsert": _batch_quality_document(artifact_id)},
            upsert=True,
        )
        self._database["meta_lineage_edges"].update_one(
            {"_id": _batch_lineage_id(artifact_id)},
            {"$setOnInsert": _batch_lineage_document(canonical, artifact_id)},
            upsert=True,
        )
        return DividendWriteResult(artifact_id, len(events), inserted)

    def _write_events(self, events: tuple[DividendEvent, ...]) -> int:
        if not events:
            return 0
        inserted = (
            self._database["pit_dividend_events"]
            .bulk_write(
                [
                    UpdateOne(
                        {"_id": event.event_id},
                        {"$setOnInsert": dividend_event_document(event)},
                        upsert=True,
                    )
                    for event in events
                ],
                ordered=False,
            )
            .upserted_count
        )
        self._database["meta_quality_reports"].bulk_write(
            [
                UpdateOne(
                    {"_id": event.quality_report_id},
                    {"$setOnInsert": _event_quality_document(event)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        self._database["meta_lineage_edges"].bulk_write(
            [
                UpdateOne(
                    {"_id": _event_lineage_id(event)},
                    {"$setOnInsert": dividend_lineage_document(event)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        return inserted


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


def dividend_lineage_document(event: DividendEvent) -> BsonDocument:
    """Map every exposed stage field to an exact Tushare dividend column."""
    lineage_id = _event_lineage_id(event)
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
        "parameters_sha256": hashlib.sha256(event.event_type.value.encode()).hexdigest(),
        "field_mappings": list(_field_mappings(event.event_type)),
        "executed_at": event.ingested_at,
    }


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


def _event_quality_document(event: DividendEvent) -> BsonDocument:
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


def dividend_batch_artifact_id(canonical_artifact_id: str) -> str:
    """Derive the stable PIT batch identity from one canonical artifact."""
    digest = hashlib.sha256(f"{canonical_artifact_id}|dividend_pit|1.0.0".encode()).hexdigest()
    return f"dividend_pit_batch_{digest}"


def _batch_quality_id(artifact_id: str) -> str:
    return f"quality_{hashlib.sha256(artifact_id.encode()).hexdigest()}"


def _batch_quality_document(artifact_id: str) -> BsonDocument:
    return {
        "_id": _batch_quality_id(artifact_id),
        "quality_report_id": _batch_quality_id(artifact_id),
        "artifact_id": artifact_id,
        "rulebook_version": "1.1.0",
        "checks": ["stage_projection_complete", "empty_batch_evidence"],
        "passed": True,
        "failure_codes": [],
        "checked_at": datetime.now(_SHANGHAI),
    }


def _batch_lineage_id(artifact_id: str) -> str:
    return f"lineage_{hashlib.sha256(artifact_id.encode()).hexdigest()}"


def _batch_lineage_document(canonical: CanonicalBatch, artifact_id: str) -> BsonDocument:
    lineage_id = _batch_lineage_id(artifact_id)
    return {
        "_id": lineage_id,
        "lineage_edge_id": lineage_id,
        "upstream_artifact_id": canonical.artifact_id,
        "downstream_artifact_id": artifact_id,
        "transform_name": "dividend_row_to_pit_events",
        "transform_version": "1.0.0",
        "code_commit": "workspace_unversioned",
        "input_schema_ids": [canonical.schema_manifest_id],
        "output_schema_id": canonical.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"stage_split").hexdigest(),
        "field_mappings": [f"pit_dividend_events.*<-{canonical.collection}.*"],
        "executed_at": datetime.now(_SHANGHAI),
    }


def _event_lineage_id(event: DividendEvent) -> str:
    digest = hashlib.sha256(f"{event.event_id}|lineage".encode()).hexdigest()
    return f"lineage_{digest}"
