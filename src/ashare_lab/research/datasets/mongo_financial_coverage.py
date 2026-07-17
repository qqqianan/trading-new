"""Financial PIT coverage including zero-event Raw batch evidence."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from ashare_lab.research.datasets.coverage_models import ComponentCoverage, DatasetComponent
from ashare_lab.research.datasets.mongo_evidence import (
    EvidenceCollection,
    MongoDatasetEvidenceReader,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.schema_registry import SchemaRegistry
    from ashare_lab.research.datasets.batch_coverage import GovernedBatchEvidence
    from ashare_lab.research.datasets.mongo_batch_coverage import MongoBatchCoverageReader

_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_BATCH_SIZE: Final = 1_000


class _RangeParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    start_date: str
    end_date: str


class _SnapshotDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    request_params_canonical: str


class _PitLineageDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    lineage_edge_id: str
    upstream_artifact_id: str
    downstream_artifact_id: str
    code_commit: str


class _QualityDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    artifact_id: str
    passed: bool


class MongoFinancialCoverageReader:
    """Require event and empty-batch evidence across every financial request."""

    def __init__(
        self,
        database: Database[BsonDocument],
        batch_reader: MongoBatchCoverageReader,
    ) -> None:
        """Bind the shared canonical batch reader to the same database."""
        self._database = database
        self._batch_reader = batch_reader
        self._events = MongoDatasetEvidenceReader(database)

    def component(
        self,
        registry: SchemaRegistry,
        requested_end: date,
    ) -> ComponentCoverage:
        """Audit Raw, canonical, PIT batch, and PIT event evidence without sampling."""
        documents = tuple(
            _SnapshotDocument.model_validate(document)
            for document in self._database["meta_source_snapshots"].find(
                {
                    "endpoint": "fina_indicator",
                    "schema_manifest_id": registry.manifest_id,
                    "status": "ACCEPTED",
                }
            )
        )
        snapshot_ids = tuple(sorted(item.snapshot_id for item in documents))
        canonical = self._batch_reader.batch_evidence(snapshot_ids, registry.manifest_id)
        canonical_by_snapshot = {item.snapshot_id: item for item in canonical}
        canonical_artifacts = tuple(
            sorted(
                {artifact for item in canonical for artifact in item.quality_evidenced_artifact_ids}
            )
        )
        pit_lineage = tuple(
            _PitLineageDocument.model_validate(document)
            for document in self._find_batched(
                "meta_lineage_edges",
                "upstream_artifact_id",
                canonical_artifacts,
                {"transform_name": "financial_indicator_row_to_pit_version"},
            )
        )
        pit_artifacts = tuple(sorted({item.downstream_artifact_id for item in pit_lineage}))
        quality = tuple(
            _QualityDocument.model_validate(document)
            for document in self._find_batched(
                "meta_quality_reports",
                "artifact_id",
                pit_artifacts,
            )
        )
        passed = {item.artifact_id for item in quality if item.passed}
        qualified_pit = tuple(
            item
            for item in pit_lineage
            if _COMMIT_PATTERN.fullmatch(item.code_commit) and item.downstream_artifact_id in passed
        )
        qualified_upstream = {item.upstream_artifact_id for item in qualified_pit}
        valid_snapshots = tuple(
            document
            for document in documents
            if _canonical_has_pit(
                canonical_by_snapshot.get(document.snapshot_id),
                qualified_upstream,
            )
        )
        audit = self._events.audit_collection(
            EvidenceCollection.FINANCIAL_INDICATORS,
            registry.manifest_id,
        )
        blockers = set(audit.blockers)
        if not documents:
            blockers.add("empty_batch_evidence")
        if len(valid_snapshots) != len(documents):
            blockers.add("missing_pit_batch_evidence")
        ranges = tuple(
            _RangeParams.model_validate_json(item.request_params_canonical)
            for item in valid_snapshots
        )
        start = max((_date(item.start_date) for item in ranges), default=None)
        observed_end = min((_date(item.end_date) for item in ranges), default=None)
        end = min(observed_end, requested_end) if observed_end is not None else None
        lineage_ids = {
            *(item.lineage_edge_id for item in qualified_pit),
            *(edge for item in canonical for edge in item.versioned_lineage_edge_ids),
            *audit.lineage_edge_ids,
        }
        source_ids = {
            *(item.snapshot_id for item in valid_snapshots),
            *audit.source_snapshot_ids,
        }
        normalized_blockers = tuple(sorted(blockers))
        return ComponentCoverage(
            component=DatasetComponent.FINANCIALS,
            start_date=start,
            end_date=end,
            schema_manifest_ids=audit.schema_manifest_ids,
            source_snapshot_ids=tuple(sorted(source_ids)),
            lineage_edge_ids=tuple(sorted(lineage_ids)),
            quality_passed=audit.quality_passed and not normalized_blockers,
            point_in_time=audit.point_in_time and not normalized_blockers,
            blockers=normalized_blockers,
        )

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


def _canonical_has_pit(
    batch: GovernedBatchEvidence | None,
    qualified_upstream: set[str],
) -> bool:
    return batch is not None and any(
        artifact in qualified_upstream for artifact in batch.quality_evidenced_artifact_ids
    )


def _date(raw: str) -> date:
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
