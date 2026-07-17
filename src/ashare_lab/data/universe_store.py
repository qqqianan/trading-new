"""MongoDB persistence for point-in-time security events and evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from pymongo import MongoClient, UpdateOne

from ashare_lab.code_identity import load_git_commit
from ashare_lab.data.universe import (
    SecurityEvent,
    SecurityEventType,
    SecurityState,
    select_security_states,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument


@dataclass(frozen=True, slots=True)
class UniverseEventWriteResult:
    """Observable counts from one idempotent event write."""

    event_count: int
    inserted_count: int


class _StoredSecurityEvent(BaseModel):
    """Parse one untrusted Mongo event document into its closed contract."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str
    ts_code: str
    event_type: SecurityEventType
    effective_at: dt.datetime
    available_at: dt.datetime
    ingested_at: dt.datetime
    name: str | None
    is_st: bool | None
    source_endpoint: str
    source_snapshot_id: str
    source_row_sha256: str
    input_schema_manifest_id: str
    schema_manifest_id: str
    transform_name: str
    transform_version: str
    quality_status: str
    quality_report_id: str


class MongoUniverseEventStore:
    """Append PIT events together with immutable quality and lineage evidence."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind the event store only to the isolated governed database."""
        if database_name != "ashare_quant":
            msg = "universe event store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write(self, events: tuple[SecurityEvent, ...]) -> UniverseEventWriteResult:
        """Persist events and their evidence idempotently."""
        if not events:
            return UniverseEventWriteResult(event_count=0, inserted_count=0)
        code_commit = load_git_commit(Path.cwd())
        inserted = (
            self._database["pit_security_events"]
            .bulk_write(
                [
                    UpdateOne(
                        {"_id": event.event_id},
                        {"$setOnInsert": universe_event_document(event)},
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
                    {"$setOnInsert": _quality_document(event)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        self._database["meta_lineage_edges"].bulk_write(
            [
                UpdateOne(
                    {"_id": _lineage_id(event, code_commit)},
                    {"$setOnInsert": universe_lineage_document(event, code_commit)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        return UniverseEventWriteResult(event_count=len(events), inserted_count=inserted)

    def load_events(self, schema_manifest_id: str) -> tuple[SecurityEvent, ...]:
        """Load only accepted events from one exact schema identity."""
        documents = self._database["pit_security_events"].find(
            {"schema_manifest_id": schema_manifest_id, "quality_status": "ACCEPTED"}
        )
        return tuple(security_event_from_document(document) for document in documents)

    def states_at(
        self,
        schema_manifest_id: str,
        decision_time: dt.datetime,
    ) -> tuple[SecurityState, ...]:
        """Return listed states through the mandatory point-in-time fold."""
        return select_security_states(self.load_events(schema_manifest_id), decision_time)


def universe_event_document(event: SecurityEvent) -> BsonDocument:
    """Serialize one event without carrying future lifecycle outcomes."""
    return {
        "_id": event.event_id,
        "event_id": event.event_id,
        "ts_code": event.ts_code,
        "event_type": event.event_type.value,
        "effective_at": event.effective_at,
        "available_at": event.available_at,
        "ingested_at": event.ingested_at,
        "name": event.name,
        "is_st": event.is_st,
        "source_endpoint": event.source_endpoint,
        "source_snapshot_id": event.source_snapshot_id,
        "source_row_sha256": event.source_row_sha256,
        "input_schema_manifest_id": event.input_schema_manifest_id,
        "schema_manifest_id": event.schema_manifest_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "quality_status": event.quality_status,
        "quality_report_id": event.quality_report_id,
    }


def security_event_from_document(document: BsonDocument) -> SecurityEvent:
    """Parse a Mongo document without permitting dynamic event variants."""
    stored = _StoredSecurityEvent.model_validate(document)
    return SecurityEvent(
        event_id=stored.event_id,
        ts_code=stored.ts_code,
        event_type=stored.event_type,
        effective_at=_restore_mongo_time(stored.effective_at),
        available_at=_restore_mongo_time(stored.available_at),
        ingested_at=_restore_mongo_time(stored.ingested_at),
        name=stored.name,
        is_st=stored.is_st,
        source_endpoint=stored.source_endpoint,
        source_snapshot_id=stored.source_snapshot_id,
        source_row_sha256=stored.source_row_sha256,
        input_schema_manifest_id=stored.input_schema_manifest_id,
        schema_manifest_id=stored.schema_manifest_id,
        transform_name=stored.transform_name,
        transform_version=stored.transform_version,
        quality_status=stored.quality_status,
        quality_report_id=stored.quality_report_id,
    )


def universe_lineage_document(event: SecurityEvent, code_commit: str) -> BsonDocument:
    """Bind every derived field to explicit provider fields and one Raw snapshot."""
    edge_id = _lineage_id(event, code_commit)
    return {
        "_id": edge_id,
        "lineage_edge_id": edge_id,
        "upstream_artifact_id": event.source_snapshot_id,
        "downstream_artifact_id": event.event_id,
        "transform_name": event.transform_name,
        "transform_version": event.transform_version,
        "code_commit": code_commit,
        "input_schema_ids": [event.input_schema_manifest_id],
        "output_schema_id": event.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(event.event_type.value.encode()).hexdigest(),
        "field_mappings": list(_field_mappings(event)),
        "executed_at": event.ingested_at,
    }


def _quality_document(event: SecurityEvent) -> BsonDocument:
    return {
        "_id": event.quality_report_id,
        "quality_report_id": event.quality_report_id,
        "artifact_id": event.event_id,
        "rulebook_version": "1.1.0",
        "checks": ["lifecycle_date", "point_in_time_availability", "field_lineage"],
        "passed": event.quality_status == "ACCEPTED",
        "failure_codes": [],
        "checked_at": event.ingested_at,
    }


def _field_mappings(event: SecurityEvent) -> tuple[str, ...]:
    raw = f"raw_tushare_{event.source_endpoint}.payload"
    common = (f"pit_security_events.ts_code<-{raw}.ts_code",)
    match event.event_type:
        case SecurityEventType.LISTED:
            specific = (f"pit_security_events.effective_at<-{raw}.list_date",)
        case SecurityEventType.FIRST_TRADED:
            specific = (f"pit_security_events.effective_at<-{raw}.trade_date",)
        case SecurityEventType.DELISTED:
            specific = (f"pit_security_events.effective_at<-{raw}.delist_date",)
        case SecurityEventType.NAME_STATUS:
            date_field = "start_date" if event.source_endpoint == "namechange" else "snapshot_time"
            specific = (
                f"pit_security_events.effective_at<-{raw}.{date_field}",
                f"pit_security_events.name<-{raw}.name",
                f"pit_security_events.is_st<-contains_st({raw}.name)",
            )
    return common + specific


def _lineage_id(event: SecurityEvent, code_commit: str) -> str:
    digest = hashlib.sha256(f"{event.event_id}|lineage|{code_commit}".encode()).hexdigest()
    return f"lineage_{digest}"


def _restore_mongo_time(value: dt.datetime) -> dt.datetime:
    utc_value = value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)
    return utc_value.astimezone(_SHANGHAI)
