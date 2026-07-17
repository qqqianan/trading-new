"""Append-only Mongo persistence for dataset qualification artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymongo import MongoClient, UpdateOne

from ashare_lab.research.datasets.coverage import (
    ComponentCoverage,
    DatasetCoverageError,
    DatasetCoverageReport,
    DatasetInputManifest,
    QualificationStatus,
)
from ashare_lab.research.datasets.identity_chunk_store import (
    identity_chunk_document,
    identity_reference_fields,
    owner_identity_chunks,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument


@dataclass(frozen=True, slots=True)
class DatasetArtifactWriteResult:
    """Counts from one idempotent qualification artifact write."""

    report_count: int
    component_count: int
    component_inserted_count: int
    manifest_count: int
    identity_chunk_count: int = 0
    identity_chunk_inserted_count: int = 0


class MongoDatasetArtifactStore:
    """Persist immutable coverage reports and qualified input manifests."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind only to the governed isolated database."""
        if database_name != "ashare_quant":
            msg = "dataset artifact store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write(
        self,
        report: DatasetCoverageReport,
        manifest: DatasetInputManifest | None,
        recorded_at: datetime,
    ) -> DatasetArtifactWriteResult:
        """Append one report, its matrix rows, and optional qualified manifest."""
        if manifest is not None and report.status is not QualificationStatus.QUALIFIED:
            detail = "blocked coverage report cannot persist an input manifest"
            raise DatasetCoverageError(detail)
        self._database["dataset_coverage_reports"].update_one(
            {"_id": report.report_id},
            {"$setOnInsert": coverage_report_document(report, recorded_at)},
            upsert=True,
        )
        chunks = tuple(
            chunk
            for component in report.components
            for chunk in owner_identity_chunks(
                _component_id(report.report_id, component.component.value),
                component.source_snapshot_ids,
                component.lineage_edge_ids,
            )
        )
        if manifest is not None:
            chunks += owner_identity_chunks(
                manifest.manifest_id,
                manifest.source_snapshot_ids,
                manifest.lineage_edge_ids,
            )
        chunk_operations = [
            UpdateOne(
                {"_id": chunk.chunk_id},
                {"$setOnInsert": identity_chunk_document(chunk)},
                upsert=True,
            )
            for chunk in chunks
        ]
        chunks_inserted = (
            self._database["dataset_identity_chunks"]
            .bulk_write(chunk_operations, ordered=False)
            .upserted_count
            if chunk_operations
            else 0
        )
        operations = [
            UpdateOne(
                {"_id": _component_id(report.report_id, component.component.value)},
                {"$setOnInsert": _component_document(report.report_id, component)},
                upsert=True,
            )
            for component in report.components
        ]
        inserted = (
            self._database["dataset_component_coverage"]
            .bulk_write(operations, ordered=False)
            .upserted_count
            if operations
            else 0
        )
        if manifest is not None:
            self._database["dataset_input_manifests"].update_one(
                {"_id": manifest.manifest_id},
                {"$setOnInsert": input_manifest_document(manifest, recorded_at)},
                upsert=True,
            )
        return DatasetArtifactWriteResult(
            report_count=1,
            component_count=len(report.components),
            component_inserted_count=inserted,
            manifest_count=1 if manifest is not None else 0,
            identity_chunk_count=len(chunks),
            identity_chunk_inserted_count=chunks_inserted,
        )


def coverage_report_document(
    report: DatasetCoverageReport,
    recorded_at: datetime,
) -> BsonDocument:
    """Serialize one closed report document."""
    return {
        "_id": report.report_id,
        "report_id": report.report_id,
        "requested_start": report.request.start_date.strftime("%Y%m%d"),
        "requested_end": report.request.end_date.strftime("%Y%m%d"),
        "required_components": [item.value for item in report.request.required_components],
        "status": report.status.value,
        "qualified_start": (
            report.qualified_start.strftime("%Y%m%d") if report.qualified_start else None
        ),
        "qualified_end": (
            report.qualified_end.strftime("%Y%m%d") if report.qualified_end else None
        ),
        "blockers": list(report.blockers),
        "rulebook_version": "1.1.0",
        "computed_at": recorded_at,
    }


def input_manifest_document(
    manifest: DatasetInputManifest,
    recorded_at: datetime,
) -> BsonDocument:
    """Serialize one closed input manifest document."""
    document: BsonDocument = {
        "_id": manifest.manifest_id,
        "manifest_id": manifest.manifest_id,
        "coverage_report_id": manifest.coverage_report_id,
        "schema_manifest_id": manifest.schema_manifest_id,
        "lineage_manifest_id": manifest.lineage_manifest_id,
        "input_schema_manifest_ids": list(manifest.input_schema_manifest_ids),
        "created_at": recorded_at,
    }
    document.update(
        identity_reference_fields(
            manifest.manifest_id,
            manifest.source_snapshot_ids,
            manifest.lineage_edge_ids,
        )
    )
    return document


def _component_id(report_id: str, component: str) -> str:
    digest = hashlib.sha256(f"{report_id}|{component}".encode()).hexdigest()
    return f"component_coverage_{digest}"


def _component_document(
    report_id: str,
    component: ComponentCoverage,
) -> BsonDocument:
    identity = _component_id(report_id, component.component.value)
    document: BsonDocument = {
        "_id": identity,
        "component_coverage_id": identity,
        "report_id": report_id,
        "component": component.component.value,
        "start_date": component.start_date.strftime("%Y%m%d") if component.start_date else None,
        "end_date": component.end_date.strftime("%Y%m%d") if component.end_date else None,
        "schema_manifest_ids": list(component.schema_manifest_ids),
        "quality_passed": component.quality_passed,
        "point_in_time": component.point_in_time,
        "blockers": list(component.blockers),
    }
    document.update(
        identity_reference_fields(
            identity,
            component.source_snapshot_ids,
            component.lineage_edge_ids,
        )
    )
    return document
