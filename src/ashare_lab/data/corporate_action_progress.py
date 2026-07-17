"""Evidence-based resume detection for dividend announcement dates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict
from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.corporate_action_store import dividend_batch_artifact_id

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.schema_registry import SchemaRegistry


class _SnapshotEvidence(BaseModel):
    """Accepted Raw fields needed to recover one announcement date."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    request_params_canonical: str


class _DividendParams(BaseModel):
    """Typed request projection for one announcement date."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ann_date: str


class _CanonicalLineage(BaseModel):
    """Canonical artifact identity derived from one accepted Raw snapshot."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    downstream_artifact_id: str


def completed_dividend_dates(
    database: Database[BsonDocument],
    schema_manifest_id: str,
    start_date: str,
    end_date: str,
) -> frozenset[str]:
    """Return dates with accepted Raw, canonical lineage, and passed PIT evidence."""
    completed: set[str] = set()
    snapshots = database["meta_source_snapshots"].find(
        {
            "endpoint": "dividend",
            "schema_manifest_id": schema_manifest_id,
            "status": "ACCEPTED",
        }
    )
    for document in snapshots:
        snapshot = _SnapshotEvidence.model_validate(document)
        params = _DividendParams.model_validate_json(snapshot.request_params_canonical)
        if not start_date <= params.ann_date <= end_date:
            continue
        canonical_document = database["meta_lineage_edges"].find_one(
            {
                "upstream_artifact_id": snapshot.snapshot_id,
                "output_schema_id": schema_manifest_id,
                "transform_name": "tushare_raw_to_canonical",
            }
        )
        if canonical_document is None:
            continue
        canonical = _CanonicalLineage.model_validate(canonical_document)
        batch_id = dividend_batch_artifact_id(canonical.downstream_artifact_id)
        pit_lineage = database["meta_lineage_edges"].find_one(
            {
                "upstream_artifact_id": canonical.downstream_artifact_id,
                "downstream_artifact_id": batch_id,
                "output_schema_id": schema_manifest_id,
            },
            {"_id": 1},
        )
        quality = database["meta_quality_reports"].find_one(
            {"artifact_id": batch_id, "passed": True},
            {"_id": 1},
        )
        if pit_lineage is not None and quality is not None:
            completed.add(params.ann_date)
    return frozenset(completed)


def load_completed_dividend_dates(
    registry: SchemaRegistry,
    start_date: str,
    end_date: str,
) -> frozenset[str]:
    """Load completed dates through an owned MongoDB connection."""
    settings = DataSettings()
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        return completed_dividend_dates(
            mongo[settings.mongodb_database],
            registry.manifest_id,
            start_date,
            end_date,
        )
