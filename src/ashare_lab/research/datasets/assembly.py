"""Fail-closed assembly of materialized features and labels into DatasetSpec."""

import hashlib
from dataclasses import dataclass
from datetime import date

from ashare_lab.research.datasets.coverage import (
    DatasetCoverageReport,
    DatasetInputManifest,
    QualificationStatus,
)
from ashare_lab.research.datasets.spec import DatasetSpec, FeatureRef, LabelRef


@dataclass(frozen=True, slots=True)
class FeatureArtifactEvidence:
    """One materialized feature and its output lineage."""

    feature: FeatureRef
    artifact_id: str
    lineage_edge_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabelArtifactEvidence:
    """One physically isolated label artifact and its output lineage."""

    label: LabelRef
    artifact_id: str
    lineage_edge_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetAssemblyRequest:
    """Final universe identity and bounded materialization interval."""

    universe_version: str
    start_date: date
    end_date: date


class DatasetAssemblyError(Exception):
    """Materialized dataset evidence is incomplete or inconsistent."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a fail-closed assembly error."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the concrete missing or inconsistent evidence."""
        return self.detail


def assemble_dataset_spec(
    report: DatasetCoverageReport,
    inputs: DatasetInputManifest,
    features: tuple[FeatureArtifactEvidence, ...],
    label: LabelArtifactEvidence,
    request: DatasetAssemblyRequest,
) -> DatasetSpec:
    """Create DatasetSpec only after feature and label artifacts have lineage."""
    if report.status is not QualificationStatus.QUALIFIED:
        detail = "dataset coverage report is not qualified"
        raise DatasetAssemblyError(detail)
    if inputs.coverage_report_id != report.report_id:
        detail = "input manifest does not belong to the coverage report"
        raise DatasetAssemblyError(detail)
    if request.start_date < report.request.start_date or request.end_date > report.request.end_date:
        detail = "dataset dates exceed the qualified requested interval"
        raise DatasetAssemblyError(detail)
    if request.start_date > request.end_date:
        detail = "dataset start_date exceeds end_date"
        raise DatasetAssemblyError(detail)
    if not features:
        detail = "dataset has no materialized feature artifacts"
        raise DatasetAssemblyError(detail)
    feature_keys = tuple((item.feature.name, item.feature.version) for item in features)
    if len(set(feature_keys)) != len(feature_keys):
        detail = "dataset contains duplicate feature definitions"
        raise DatasetAssemblyError(detail)
    if any(item.artifact_id == "" or not item.lineage_edge_ids for item in features):
        detail = "feature artifact or feature lineage is incomplete"
        raise DatasetAssemblyError(detail)
    if label.artifact_id == "" or not label.lineage_edge_ids:
        detail = "label artifact or label lineage is incomplete"
        raise DatasetAssemblyError(detail)
    feature_lineage = tuple(sorted({edge for item in features for edge in item.lineage_edge_ids}))
    label_lineage = tuple(sorted(set(label.lineage_edge_ids)))
    if set(feature_lineage) & set(label_lineage):
        detail = "feature and label lineage branches overlap"
        raise DatasetAssemblyError(detail)
    all_lineage = tuple(sorted({*inputs.lineage_edge_ids, *feature_lineage, *label_lineage}))
    lineage_digest = hashlib.sha256("|".join(all_lineage).encode()).hexdigest()
    return DatasetSpec(
        rulebook_version="1.1.0",
        coverage_report_id=report.report_id,
        input_manifest_id=inputs.manifest_id,
        source_snapshot_ids=inputs.source_snapshot_ids,
        schema_manifest_id=inputs.schema_manifest_id,
        input_schema_manifest_ids=inputs.input_schema_manifest_ids,
        lineage_manifest_id=f"lineage_{lineage_digest}",
        feature_artifact_ids=tuple(item.artifact_id for item in features),
        feature_lineage_edge_ids=feature_lineage,
        label_artifact_id=label.artifact_id,
        label_lineage_edge_ids=label_lineage,
        universe_version=request.universe_version,
        features=tuple(item.feature for item in features),
        label=label.label,
        start_date=request.start_date,
        end_date=request.end_date,
    )
