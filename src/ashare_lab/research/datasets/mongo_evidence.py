"""Mongo boundary for auditing governed canonical and PIT artifact evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.research.datasets.evidence import (
    ArtifactEvidence,
    ArtifactEvidenceAudit,
    LineageEvidence,
    QualityEvidence,
    SnapshotEvidence,
    audit_artifact_evidence,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument

_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_BATCH_SIZE: Final = 1_000


@unique
class EvidenceCollection(StrEnum):
    """Closed artifact collections eligible for dataset evidence audit."""

    UNIVERSE = "pit_security_events"
    FINANCIAL_INDICATORS = "pit_financial_indicators"
    INDUSTRY_MEMBERSHIPS = "pit_industry_memberships"


class _ArtifactDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    artifact_id: str = Field(validation_alias="_id")
    source_snapshot_id: str
    input_schema_manifest_id: str | None = None
    schema_manifest_id: str
    quality_report_id: str
    quality_status: str
    available_at: datetime


class _SnapshotDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    schema_manifest_id: str
    status: str


class _QualityDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    quality_report_id: str
    artifact_id: str
    passed: bool


class _LineageDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    lineage_edge_id: str
    upstream_artifact_id: str
    downstream_artifact_id: str
    output_schema_id: str
    code_commit: str


class DatasetEvidenceReaderError(Exception):
    """The Mongo evidence adapter is bound outside its owned database."""

    __slots__ = ("database_name",)

    def __init__(self, database_name: str) -> None:
        """Record the rejected database without exposing connection credentials."""
        super().__init__()
        self.database_name = database_name

    def __str__(self) -> str:
        """Explain the fixed database isolation rule."""
        return f"dataset evidence reader requires ashare_quant, got {self.database_name}"


class MongoDatasetEvidenceReader:
    """Read evidence only from the isolated governed database."""

    def __init__(self, database: Database[BsonDocument]) -> None:
        """Bind the reader without taking ownership of the client connection."""
        if database.name != "ashare_quant":
            raise DatasetEvidenceReaderError(database.name)
        self._database = database

    def audit_collection(
        self,
        collection: EvidenceCollection,
        schema_manifest_id: str,
    ) -> ArtifactEvidenceAudit:
        """Audit every artifact in one exact schema without sampling."""
        documents = self._database[collection.value].find(
            {"schema_manifest_id": schema_manifest_id},
            {
                "_id": 1,
                "source_snapshot_id": 1,
                "input_schema_manifest_id": 1,
                "schema_manifest_id": 1,
                "quality_report_id": 1,
                "quality_status": 1,
                "available_at": 1,
            },
        )
        artifacts = tuple(_artifact_evidence(document) for document in documents)
        source_ids = tuple(sorted({item.source_snapshot_id for item in artifacts}))
        quality_ids = tuple(sorted({item.quality_report_id for item in artifacts}))
        artifact_ids = tuple(item.artifact_id for item in artifacts)
        snapshots = tuple(
            _snapshot_evidence(document)
            for document in self._find_batched(
                "meta_source_snapshots",
                "snapshot_id",
                source_ids,
            )
        )
        quality = tuple(
            _quality_evidence(document)
            for document in self._find_batched(
                "meta_quality_reports",
                "quality_report_id",
                quality_ids,
            )
        )
        lineage = tuple(
            _lineage_evidence(document)
            for document in self._find_batched(
                "meta_lineage_edges",
                "downstream_artifact_id",
                artifact_ids,
            )
        )
        return audit_artifact_evidence(artifacts, snapshots, quality, lineage)

    def _find_batched(
        self,
        collection: str,
        field: str,
        values: tuple[str, ...],
    ) -> tuple[BsonDocument, ...]:
        documents: list[BsonDocument] = []
        for start in range(0, len(values), _BATCH_SIZE):
            batch = values[start : start + _BATCH_SIZE]
            documents.extend(self._database[collection].find({field: {"$in": list(batch)}}))
        return tuple(documents)


def _artifact_evidence(document: BsonDocument) -> ArtifactEvidence:
    parsed = _ArtifactDocument.model_validate(document)
    return ArtifactEvidence(
        artifact_id=parsed.artifact_id,
        source_snapshot_id=parsed.source_snapshot_id,
        input_schema_manifest_id=(parsed.input_schema_manifest_id or parsed.schema_manifest_id),
        schema_manifest_id=parsed.schema_manifest_id,
        quality_report_id=parsed.quality_report_id,
        quality_status=parsed.quality_status,
        available_at=_restore_mongo_time(parsed.available_at),
    )


def _snapshot_evidence(document: BsonDocument) -> SnapshotEvidence:
    parsed = _SnapshotDocument.model_validate(document)
    return SnapshotEvidence(parsed.snapshot_id, parsed.schema_manifest_id, parsed.status)


def _quality_evidence(document: BsonDocument) -> QualityEvidence:
    parsed = _QualityDocument.model_validate(document)
    return QualityEvidence(parsed.quality_report_id, parsed.artifact_id, parsed.passed)


def _lineage_evidence(document: BsonDocument) -> LineageEvidence:
    parsed = _LineageDocument.model_validate(document)
    return LineageEvidence(
        parsed.lineage_edge_id,
        parsed.upstream_artifact_id,
        parsed.downstream_artifact_id,
        parsed.output_schema_id,
        parsed.code_commit,
    )


def _restore_mongo_time(value: datetime) -> datetime:
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.astimezone(_SHANGHAI)
