"""Fail-closed publication of a logical DatasetSpec from immutable artifacts."""

from dataclasses import dataclass
from datetime import date

from ashare_lab.research.artifacts import ArtifactDescriptor, ArtifactKind
from ashare_lab.research.artifacts.models import ArtifactManifest
from ashare_lab.research.datasets.assembly import (
    DatasetAssemblyRequest,
    FeatureArtifactEvidence,
    LabelArtifactEvidence,
    assemble_dataset_spec,
)
from ashare_lab.research.datasets.coverage import DatasetCoverageReport, DatasetInputManifest
from ashare_lab.research.datasets.spec import FeatureRef, LabelRef
from ashare_lab.research.datasets.spec_store import DatasetSpecDescriptor, DatasetSpecStore


@dataclass(frozen=True, slots=True)
class MaterializedFeature:
    """One registered feature bound to its descriptor and exact manifest."""

    feature: FeatureRef
    descriptor: ArtifactDescriptor
    manifest: ArtifactManifest


@dataclass(frozen=True, slots=True)
class MaterializedLabel:
    """One registered label bound to its physically separate artifact."""

    label: LabelRef
    descriptor: ArtifactDescriptor
    manifest: ArtifactManifest


@dataclass(frozen=True, slots=True)
class DatasetPublicationRequest:
    """All qualified source and materialized artifact identities."""

    report: DatasetCoverageReport
    inputs: DatasetInputManifest
    universe: ArtifactDescriptor
    universe_manifest: ArtifactManifest
    features: tuple[MaterializedFeature, ...]
    label: MaterializedLabel
    start_date: date
    end_date: date


class DatasetPublicationError(Exception):
    """One materialized artifact is inconsistent with the requested dataset."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one stable publication blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the fail-closed rule and concrete identity detail."""
        return f"dataset_publication: {self.detail}"


def publish_dataset_spec(
    store: DatasetSpecStore,
    request: DatasetPublicationRequest,
) -> DatasetSpecDescriptor:
    """Validate all branches, assemble DatasetSpec, and publish it atomically."""
    _validate_manifest(request.universe, request.universe_manifest, ArtifactKind.UNIVERSE)
    _validate_upstreams(
        request.universe_manifest,
        (request.inputs.manifest_id,),
        (request.inputs.lineage_manifest_id,),
    )
    if not request.features:
        detail = "no registered feature artifacts"
        raise DatasetPublicationError(detail)
    for item in request.features:
        _validate_manifest(item.descriptor, item.manifest, ArtifactKind.FEATURE)
        _validate_materialized_branch(
            item.descriptor,
            item.manifest,
            item.feature.version,
            request,
        )
    _validate_manifest(request.label.descriptor, request.label.manifest, ArtifactKind.LABEL)
    _validate_materialized_branch(
        request.label.descriptor,
        request.label.manifest,
        request.label.label.version,
        request,
    )
    spec = assemble_dataset_spec(
        request.report,
        request.inputs,
        tuple(
            FeatureArtifactEvidence(
                item.feature,
                item.descriptor.artifact_id,
                (item.manifest.lineage_edge_id,),
            )
            for item in request.features
        ),
        LabelArtifactEvidence(
            request.label.label,
            request.label.descriptor.artifact_id,
            (request.label.manifest.lineage_edge_id,),
        ),
        DatasetAssemblyRequest(
            request.universe.artifact_id,
            request.start_date,
            request.end_date,
        ),
    )
    return store.write(spec)


def _validate_materialized_branch(
    descriptor: ArtifactDescriptor,
    manifest: ArtifactManifest,
    declared_version: str,
    request: DatasetPublicationRequest,
) -> None:
    if descriptor.row_count != request.universe.row_count:
        detail = f"artifact row count differs from universe: {descriptor.artifact_id}"
        raise DatasetPublicationError(detail)
    if manifest.transform_version != declared_version:
        detail = f"artifact version mismatch: {descriptor.artifact_id}"
        raise DatasetPublicationError(detail)
    _validate_upstreams(
        manifest,
        (request.inputs.manifest_id, request.universe.artifact_id),
        (request.inputs.lineage_manifest_id, request.universe.lineage_edge_id),
    )


def _validate_manifest(
    descriptor: ArtifactDescriptor,
    manifest: ArtifactManifest,
    kind: ArtifactKind,
) -> None:
    if (
        descriptor.artifact_id != manifest.artifact_id
        or descriptor.kind is not kind
        or manifest.kind is not kind
        or descriptor.schema_manifest_id != manifest.schema_manifest_id
        or descriptor.lineage_edge_id != manifest.lineage_edge_id
        or descriptor.data_sha256 != manifest.data_sha256
        or descriptor.row_count != manifest.row_count
    ):
        detail = f"descriptor and manifest mismatch: {descriptor.artifact_id}"
        raise DatasetPublicationError(detail)


def _validate_upstreams(
    manifest: ArtifactManifest,
    artifact_ids: tuple[str, ...],
    lineage_ids: tuple[str, ...],
) -> None:
    if manifest.upstream_artifact_ids != artifact_ids or (
        manifest.upstream_lineage_edge_ids != lineage_ids
    ):
        detail = f"upstream identity mismatch: {manifest.artifact_id}"
        raise DatasetPublicationError(detail)
