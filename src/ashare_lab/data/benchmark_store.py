"""Mongo persistence for index-weight PIT events and monthly evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pymongo import MongoClient, UpdateOne

from ashare_lab.code_identity import load_git_commit
from ashare_lab.data.benchmark_documents import (
    index_weight_document,
    index_weight_lineage,
    index_weight_lineage_id,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.benchmark_weights import IndexWeightEvent
    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class BenchmarkWriteResult:
    """Counts and stable identity from one monthly PIT projection."""

    batch_artifact_id: str
    event_count: int
    inserted_count: int


class MongoBenchmarkWeightStore:
    """Append index weights with event and empty-month evidence."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind persistence only to the isolated governed database."""
        if database_name != "ashare_quant":
            msg = "benchmark weight store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write_batch(
        self, canonical: CanonicalBatch, events: tuple[IndexWeightEvent, ...]
    ) -> BenchmarkWriteResult:
        """Persist events and completion evidence, including empty months."""
        code_commit = load_git_commit(Path.cwd())
        inserted = self._write_events(events, code_commit)
        artifact = benchmark_weight_batch_id(canonical.artifact_id)
        self._database["meta_quality_reports"].update_one(
            {"_id": _quality_id(artifact)},
            {"$setOnInsert": _quality_document(artifact)},
            upsert=True,
        )
        self._database["meta_lineage_edges"].update_one(
            {"_id": _lineage_id(artifact)},
            {"$setOnInsert": _batch_lineage(canonical, artifact, code_commit)},
            upsert=True,
        )
        return BenchmarkWriteResult(artifact, len(events), inserted)

    def _write_events(self, events: tuple[IndexWeightEvent, ...], code_commit: str) -> int:
        if not events:
            return 0
        inserted = (
            self._database["pit_index_weights"]
            .bulk_write(
                [
                    UpdateOne(
                        {"_id": event.event_id},
                        {"$setOnInsert": index_weight_document(event)},
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
                    {"$setOnInsert": _event_quality(event)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        self._database["meta_lineage_edges"].bulk_write(
            [
                UpdateOne(
                    {"_id": index_weight_lineage_id(event)},
                    {"$setOnInsert": index_weight_lineage(event, code_commit)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        return inserted


def benchmark_weight_batch_id(canonical_id: str) -> str:
    """Derive a stable PIT batch identity from one canonical month."""
    digest = hashlib.sha256(f"{canonical_id}|index_weight_pit|1.0.0".encode()).hexdigest()
    return f"index_weight_pit_batch_{digest}"


def _event_quality(event: IndexWeightEvent) -> BsonDocument:
    return {
        "_id": event.quality_report_id,
        "quality_report_id": event.quality_report_id,
        "artifact_id": event.event_id,
        "rulebook_version": "1.1.0",
        "checks": ["single_weight_date", "weight_sum", "provider_row_cap", "field_lineage"],
        "passed": True,
        "failure_codes": [],
        "checked_at": event.ingested_at,
    }


def _quality_id(artifact: str) -> str:
    return f"quality_{hashlib.sha256(artifact.encode()).hexdigest()}"


def _quality_document(artifact: str) -> BsonDocument:
    return {
        "_id": _quality_id(artifact),
        "quality_report_id": _quality_id(artifact),
        "artifact_id": artifact,
        "rulebook_version": "1.1.0",
        "checks": ["monthly_projection_complete", "empty_month_evidence"],
        "passed": True,
        "failure_codes": [],
        "checked_at": datetime.now(_SHANGHAI),
    }


def _lineage_id(artifact: str) -> str:
    return f"lineage_{hashlib.sha256(artifact.encode()).hexdigest()}"


def _batch_lineage(
    canonical: CanonicalBatch,
    artifact: str,
    code_commit: str,
) -> BsonDocument:
    lineage = _lineage_id(artifact)
    return {
        "_id": lineage,
        "lineage_edge_id": lineage,
        "upstream_artifact_id": canonical.artifact_id,
        "downstream_artifact_id": artifact,
        "transform_name": "index_weight_row_to_pit_event",
        "transform_version": "1.0.0",
        "code_commit": code_commit,
        "input_schema_ids": [canonical.schema_manifest_id],
        "output_schema_id": canonical.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"monthly_weight_projection").hexdigest(),
        "field_mappings": [f"pit_index_weights.*<-{canonical.collection}.*"],
        "executed_at": datetime.now(_SHANGHAI),
    }
