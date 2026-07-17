"""Mongo persistence for cash-flow PIT versions and batch evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pymongo import MongoClient, UpdateOne

from ashare_lab.code_identity import load_git_commit
from ashare_lab.data.cashflow_documents import (
    cashflow_document,
    cashflow_lineage,
    cashflow_lineage_id,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch
    from ashare_lab.data.cashflows import CashflowVersion

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class CashflowWriteResult:
    """Counts and stable batch identity from one PIT projection."""

    batch_artifact_id: str
    event_count: int
    inserted_count: int


class MongoCashflowStore:
    """Append versions with event-level and empty-batch governance evidence."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind persistence only to the isolated governed database."""
        if database_name != "ashare_quant":
            msg = "cash-flow store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write_batch(
        self, canonical: CanonicalBatch, events: tuple[CashflowVersion, ...]
    ) -> CashflowWriteResult:
        """Persist all events plus completion evidence, including empty responses."""
        code_commit = load_git_commit(Path.cwd())
        inserted = self._write_events(events, code_commit)
        artifact_id = cashflow_batch_artifact_id(canonical.artifact_id)
        self._database["meta_quality_reports"].update_one(
            {"_id": _batch_quality_id(artifact_id)},
            {"$setOnInsert": _batch_quality_document(artifact_id)},
            upsert=True,
        )
        self._database["meta_lineage_edges"].update_one(
            {"_id": _batch_lineage_id(artifact_id)},
            {"$setOnInsert": _batch_lineage_document(canonical, artifact_id, code_commit)},
            upsert=True,
        )
        return CashflowWriteResult(artifact_id, len(events), inserted)

    def _write_events(self, events: tuple[CashflowVersion, ...], code_commit: str) -> int:
        if not events:
            return 0
        inserted = (
            self._database["pit_cashflow_statements"]
            .bulk_write(
                [
                    UpdateOne(
                        {"_id": e.event_id}, {"$setOnInsert": cashflow_document(e)}, upsert=True
                    )
                    for e in events
                ],
                ordered=False,
            )
            .upserted_count
        )
        self._database["meta_quality_reports"].bulk_write(
            [
                UpdateOne(
                    {"_id": e.quality_report_id}, {"$setOnInsert": _event_quality(e)}, upsert=True
                )
                for e in events
            ],
            ordered=False,
        )
        self._database["meta_lineage_edges"].bulk_write(
            [
                UpdateOne(
                    {"_id": cashflow_lineage_id(e)},
                    {"$setOnInsert": cashflow_lineage(e, code_commit)},
                    upsert=True,
                )
                for e in events
            ],
            ordered=False,
        )
        return inserted


def cashflow_batch_artifact_id(canonical_artifact_id: str) -> str:
    """Derive a stable PIT batch identity from one canonical artifact."""
    digest = hashlib.sha256(f"{canonical_artifact_id}|cashflow_pit|1.0.0".encode()).hexdigest()
    return f"cashflow_pit_batch_{digest}"


def _event_quality(event: CashflowVersion) -> BsonDocument:
    return {
        "_id": event.quality_report_id,
        "quality_report_id": event.quality_report_id,
        "artifact_id": event.event_id,
        "rulebook_version": "1.1.0",
        "checks": ["actual_announcement_clock", "version_identity", "field_lineage"],
        "passed": True,
        "failure_codes": [],
        "checked_at": event.ingested_at,
    }


def _batch_quality_id(artifact_id: str) -> str:
    return f"quality_{hashlib.sha256(artifact_id.encode()).hexdigest()}"


def _batch_quality_document(artifact_id: str) -> BsonDocument:
    return {
        "_id": _batch_quality_id(artifact_id),
        "quality_report_id": _batch_quality_id(artifact_id),
        "artifact_id": artifact_id,
        "rulebook_version": "1.1.0",
        "checks": ["version_projection_complete", "empty_security_evidence"],
        "passed": True,
        "failure_codes": [],
        "checked_at": datetime.now(_SHANGHAI),
    }


def _batch_lineage_id(artifact_id: str) -> str:
    return f"lineage_{hashlib.sha256(artifact_id.encode()).hexdigest()}"


def _batch_lineage_document(
    canonical: CanonicalBatch,
    artifact_id: str,
    code_commit: str,
) -> BsonDocument:
    lineage_id = _batch_lineage_id(artifact_id)
    return {
        "_id": lineage_id,
        "lineage_edge_id": lineage_id,
        "upstream_artifact_id": canonical.artifact_id,
        "downstream_artifact_id": artifact_id,
        "transform_name": "cashflow_row_to_pit_version",
        "transform_version": "1.0.0",
        "code_commit": code_commit,
        "input_schema_ids": [canonical.schema_manifest_id],
        "output_schema_id": canonical.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"cashflow_version_projection").hexdigest(),
        "field_mappings": [f"pit_cashflow_statements.*<-{canonical.collection}.*"],
        "executed_at": datetime.now(_SHANGHAI),
    }
