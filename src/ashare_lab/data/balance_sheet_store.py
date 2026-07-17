"""Mongo persistence for balance-sheet PIT versions and batch evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pymongo import MongoClient, UpdateOne

from ashare_lab.code_identity import load_git_commit
from ashare_lab.data.balance_sheet_documents import (
    balance_sheet_document,
    balance_sheet_lineage,
    balance_sheet_lineage_id,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.balance_sheets import BalanceSheetVersion
    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class BalanceSheetWriteResult:
    """Counts and stable batch identity from one PIT projection."""

    batch_artifact_id: str
    event_count: int
    inserted_count: int


class MongoBalanceSheetStore:
    """Append versions with event-level and empty-batch governance evidence."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind persistence only to the isolated governed database."""
        if database_name != "ashare_quant":
            msg = "balance-sheet store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write_batch(
        self,
        canonical: CanonicalBatch,
        events: tuple[BalanceSheetVersion, ...],
    ) -> BalanceSheetWriteResult:
        """Persist all events plus completion evidence, including empty responses."""
        code_commit = load_git_commit(Path.cwd())
        inserted = self._write_events(events, code_commit)
        artifact_id = balance_sheet_batch_artifact_id(canonical.artifact_id)
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
        return BalanceSheetWriteResult(artifact_id, len(events), inserted)

    def _write_events(self, events: tuple[BalanceSheetVersion, ...], code_commit: str) -> int:
        if not events:
            return 0
        inserted = (
            self._database["pit_balance_sheets"]
            .bulk_write(
                [
                    UpdateOne(
                        {"_id": event.event_id},
                        {"$setOnInsert": balance_sheet_document(event)},
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
                    {"_id": balance_sheet_lineage_id(event)},
                    {"$setOnInsert": balance_sheet_lineage(event, code_commit)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        return inserted


def balance_sheet_batch_artifact_id(canonical_artifact_id: str) -> str:
    """Derive a stable PIT batch identity from one canonical artifact."""
    digest = hashlib.sha256(f"{canonical_artifact_id}|balance_sheet_pit|1.0.0".encode()).hexdigest()
    return f"balance_sheet_pit_batch_{digest}"


def _event_quality_document(event: BalanceSheetVersion) -> BsonDocument:
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
        "transform_name": "balance_sheet_row_to_pit_version",
        "transform_version": "1.0.0",
        "code_commit": code_commit,
        "input_schema_ids": [canonical.schema_manifest_id],
        "output_schema_id": canonical.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"balance_sheet_version_projection").hexdigest(),
        "field_mappings": [f"pit_balance_sheets.*<-{canonical.collection}.*"],
        "executed_at": datetime.now(_SHANGHAI),
    }
