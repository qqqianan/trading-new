"""Mongo persistence for financial-indicator PIT versions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pymongo import MongoClient, UpdateOne

from ashare_lab.code_identity import load_git_commit
from ashare_lab.data.financial_indicator_documents import (
    financial_indicator_document,
    financial_indicator_lineage,
    financial_indicator_lineage_id,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch
    from ashare_lab.data.financial_indicators import FinancialIndicatorVersion

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class IndicatorWriteResult:
    """Counts and stable batch identity from one PIT projection."""

    batch_artifact_id: str
    event_count: int
    inserted_count: int


class MongoFinancialIndicatorStore:
    """Append indicator versions with event and empty-batch evidence."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind persistence only to the isolated governed database."""
        if database_name != "ashare_quant":
            msg = "financial-indicator store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write_batch(
        self, canonical: CanonicalBatch, events: tuple[FinancialIndicatorVersion, ...]
    ) -> IndicatorWriteResult:
        """Persist events and completion evidence, including empty responses."""
        code_commit = load_git_commit(Path.cwd())
        inserted = self._write_events(events, code_commit)
        artifact = indicator_batch_artifact_id(canonical.artifact_id)
        self._database["meta_quality_reports"].update_one(
            {"_id": _quality_id(artifact)}, {"$setOnInsert": _quality(artifact)}, upsert=True
        )
        self._database["meta_lineage_edges"].update_one(
            {"_id": _lineage_id(artifact, code_commit)},
            {"$setOnInsert": _batch_lineage(canonical, artifact, code_commit)},
            upsert=True,
        )
        return IndicatorWriteResult(artifact, len(events), inserted)

    def _write_events(
        self,
        events: tuple[FinancialIndicatorVersion, ...],
        code_commit: str,
    ) -> int:
        if not events:
            return 0
        inserted = (
            self._database["pit_financial_indicators"]
            .bulk_write(
                [
                    UpdateOne(
                        {"_id": e.event_id},
                        {"$setOnInsert": financial_indicator_document(e)},
                        upsert=True,
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
                    {"_id": financial_indicator_lineage_id(e, code_commit)},
                    {"$setOnInsert": financial_indicator_lineage(e, code_commit)},
                    upsert=True,
                )
                for e in events
            ],
            ordered=False,
        )
        return inserted


def indicator_batch_artifact_id(canonical_id: str) -> str:
    """Derive a stable PIT batch identity from one canonical artifact."""
    digest = hashlib.sha256(f"{canonical_id}|indicator_pit|1.0.0".encode()).hexdigest()
    return f"financial_indicator_pit_batch_{digest}"


def _event_quality(event: FinancialIndicatorVersion) -> BsonDocument:
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


def _quality_id(artifact: str) -> str:
    return f"quality_{hashlib.sha256(artifact.encode()).hexdigest()}"


def _quality(artifact: str) -> BsonDocument:
    return {
        "_id": _quality_id(artifact),
        "quality_report_id": _quality_id(artifact),
        "artifact_id": artifact,
        "rulebook_version": "1.1.0",
        "checks": ["version_projection_complete", "empty_security_evidence"],
        "passed": True,
        "failure_codes": [],
        "checked_at": datetime.now(_SHANGHAI),
    }


def _lineage_id(artifact: str, code_commit: str) -> str:
    return f"lineage_{hashlib.sha256(f'{artifact}|{code_commit}'.encode()).hexdigest()}"


def _batch_lineage(
    canonical: CanonicalBatch,
    artifact: str,
    code_commit: str,
) -> BsonDocument:
    lineage = _lineage_id(artifact, code_commit)
    return {
        "_id": lineage,
        "lineage_edge_id": lineage,
        "upstream_artifact_id": canonical.artifact_id,
        "downstream_artifact_id": artifact,
        "transform_name": "financial_indicator_row_to_pit_version",
        "transform_version": "1.0.0",
        "code_commit": code_commit,
        "input_schema_ids": [canonical.schema_manifest_id],
        "output_schema_id": canonical.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"indicator_version_projection").hexdigest(),
        "field_mappings": [f"pit_financial_indicators.*<-{canonical.collection}.*"],
        "executed_at": datetime.now(_SHANGHAI),
    }
