"""Mongo loading and normalization for Raw-to-canonical batch evidence."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from ashare_lab.research.datasets.batch_coverage import GovernedBatchEvidence

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument

_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_BATCH_SIZE: Final = 1_000


class AcceptedSnapshot(BaseModel):
    """Accepted Raw response fields needed by scheduled coverage readers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    endpoint: str
    request_params_canonical: str
    schema_manifest_id: str
    status: str


class _LineageDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    lineage_edge_id: str
    upstream_artifact_id: str
    downstream_artifact_id: str
    code_commit: str


class _QualityDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    artifact_id: str
    passed: bool


class MongoGovernedBatchReader:
    """Load exact Raw, canonical lineage, and batch quality identities."""

    def __init__(self, database: Database[BsonDocument]) -> None:
        """Bind without taking ownership of the Mongo client."""
        self._database = database

    def accepted_snapshots(
        self,
        schema_manifest_id: str,
        endpoints: tuple[str, ...],
    ) -> tuple[AcceptedSnapshot, ...]:
        """Load accepted current-schema responses for a closed endpoint set."""
        documents = self._database["meta_source_snapshots"].find(
            {
                "schema_manifest_id": schema_manifest_id,
                "status": "ACCEPTED",
                "endpoint": {"$in": list(endpoints)},
            }
        )
        parsed = tuple(AcceptedSnapshot.model_validate(item) for item in documents)
        return tuple(item for item in parsed if item.endpoint in endpoints)

    def batch_evidence(
        self,
        snapshot_ids: tuple[str, ...],
        schema_manifest_id: str,
    ) -> tuple[GovernedBatchEvidence, ...]:
        """Normalize accepted Raw-to-canonical evidence without adjudicating dates."""
        snapshots = tuple(
            AcceptedSnapshot.model_validate(document)
            for document in self._find_batched("meta_source_snapshots", "snapshot_id", snapshot_ids)
        )
        lineage = tuple(
            _LineageDocument.model_validate(document)
            for document in self._find_batched(
                "meta_lineage_edges",
                "upstream_artifact_id",
                snapshot_ids,
                {
                    "output_schema_id": schema_manifest_id,
                    "transform_name": "tushare_raw_to_canonical",
                },
            )
        )
        artifact_ids = tuple(sorted({item.downstream_artifact_id for item in lineage}))
        quality = tuple(
            _QualityDocument.model_validate(document)
            for document in self._find_batched("meta_quality_reports", "artifact_id", artifact_ids)
        )
        evidenced = {item.artifact_id for item in quality}
        passed = {item.artifact_id for item in quality if item.passed}
        return tuple(_governed(snapshot, lineage, evidenced, passed) for snapshot in snapshots)

    def _find_batched(
        self,
        collection: str,
        field: str,
        values: tuple[str, ...],
        extra_filter: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        documents: list[BsonDocument] = []
        for start in range(0, len(values), _BATCH_SIZE):
            query: BsonDocument = {field: {"$in": list(values[start : start + _BATCH_SIZE])}}
            if extra_filter is not None:
                query.update(extra_filter)
            documents.extend(self._database[collection].find(query))
        return tuple(documents)


def _governed(
    snapshot: AcceptedSnapshot,
    lineage: tuple[_LineageDocument, ...],
    evidenced_artifacts: set[str],
    passed_artifacts: set[str],
) -> GovernedBatchEvidence:
    owned = tuple(item for item in lineage if item.upstream_artifact_id == snapshot.snapshot_id)
    versioned = tuple(item for item in owned if _COMMIT_PATTERN.fullmatch(item.code_commit))
    qualified = tuple(item for item in versioned if item.downstream_artifact_id in passed_artifacts)
    return GovernedBatchEvidence(
        snapshot.snapshot_id,
        snapshot.endpoint,
        snapshot.schema_manifest_id,
        snapshot.status,
        tuple(sorted(item.lineage_edge_id for item in versioned)),
        tuple(sorted(item.lineage_edge_id for item in qualified)),
        tuple(sorted(item.downstream_artifact_id for item in qualified)),
        tuple(
            sorted(
                item.downstream_artifact_id
                for item in versioned
                if item.downstream_artifact_id in evidenced_artifacts
            )
        ),
    )
