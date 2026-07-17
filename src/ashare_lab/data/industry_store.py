"""Mongo persistence for observed-at industry membership intervals."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pymongo import MongoClient, UpdateOne

from ashare_lab.code_identity import load_git_commit
from ashare_lab.data.industry_documents import (
    industry_membership_document,
    industry_membership_lineage,
    industry_membership_lineage_id,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch
    from ashare_lab.data.industry_memberships import IndustryMembership

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class IndustryWriteResult:
    """Counts and stable identity from one exact industry projection."""

    batch_artifact_id: str
    event_count: int
    inserted_count: int


class MongoIndustryStore:
    """Append industry intervals plus event and batch evidence."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind persistence only to the governed isolated database."""
        if database_name != "ashare_quant":
            msg = "industry store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write_batch(
        self,
        canonical: CanonicalBatch,
        events: tuple[IndustryMembership, ...],
    ) -> IndustryWriteResult:
        """Persist intervals and completion evidence, including empty results."""
        code_commit = load_git_commit(Path.cwd())
        inserted = self._write_events(events, code_commit)
        artifact = _batch_id(canonical.artifact_id)
        self._database["meta_quality_reports"].update_one(
            {"_id": _quality_id(artifact)},
            {"$setOnInsert": _batch_quality(artifact)},
            upsert=True,
        )
        self._database["meta_lineage_edges"].update_one(
            {"_id": _lineage_id(artifact)},
            {"$setOnInsert": _batch_lineage(canonical, artifact, code_commit)},
            upsert=True,
        )
        return IndustryWriteResult(artifact, len(events), inserted)

    def _write_events(self, events: tuple[IndustryMembership, ...], code_commit: str) -> int:
        if not events:
            return 0
        inserted = (
            self._database["pit_industry_memberships"]
            .bulk_write(
                [
                    UpdateOne(
                        {"_id": event.membership_id},
                        {"$setOnInsert": industry_membership_document(event)},
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
                    {"_id": industry_membership_lineage_id(event)},
                    {"$setOnInsert": industry_membership_lineage(event, code_commit)},
                    upsert=True,
                )
                for event in events
            ],
            ordered=False,
        )
        return inserted


def _batch_id(canonical_id: str) -> str:
    digest = hashlib.sha256(f"{canonical_id}|industry_pit|1.0.0".encode()).hexdigest()
    return f"industry_pit_batch_{digest}"


def _event_quality(event: IndustryMembership) -> BsonDocument:
    return {
        "_id": event.quality_report_id,
        "quality_report_id": event.quality_report_id,
        "artifact_id": event.membership_id,
        "rulebook_version": "1.1.0",
        "checks": ["valid_interval", "observed_availability", "field_lineage"],
        "passed": True,
        "failure_codes": [],
        "checked_at": event.ingested_at,
    }


def _quality_id(artifact: str) -> str:
    return f"quality_{hashlib.sha256(artifact.encode()).hexdigest()}"


def _batch_quality(artifact: str) -> BsonDocument:
    return {
        "_id": _quality_id(artifact),
        "quality_report_id": _quality_id(artifact),
        "artifact_id": artifact,
        "rulebook_version": "1.1.0",
        "checks": ["exact_industry_request", "empty_response_evidence"],
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
    lineage_id = _lineage_id(artifact)
    return {
        "_id": lineage_id,
        "lineage_edge_id": lineage_id,
        "upstream_artifact_id": canonical.artifact_id,
        "downstream_artifact_id": artifact,
        "transform_name": "industry_member_row_to_observed_pit_interval",
        "transform_version": "1.0.0",
        "code_commit": code_commit,
        "input_schema_ids": [canonical.schema_manifest_id],
        "output_schema_id": canonical.schema_manifest_id,
        "parameters_sha256": hashlib.sha256(b"exact_l1_industry_request").hexdigest(),
        "field_mappings": [f"pit_industry_memberships.*<-{canonical.collection}.*"],
        "executed_at": datetime.now(_SHANGHAI),
    }
