"""Content identities and immutable manifests for research artifacts."""

import hashlib
from pathlib import Path

import polars as pl

from ashare_lab.research.artifacts.models import (
    ArtifactDescriptor,
    ArtifactManifest,
    ArtifactWriteRequest,
)


def artifact_id(
    request: ArtifactWriteRequest,
    data_sha256: str,
    column_names: tuple[str, ...],
) -> str:
    """Hash payload and transformation evidence into one stable identity."""
    mappings = tuple(
        (
            f"{mapping.output_field}|{mapping.upstream_artifact_id}|"
            f"{mapping.upstream_field}|{mapping.transformation}"
        )
        for mapping in sorted(request.field_mappings, key=lambda item: item.output_field)
    )
    identity = "|".join(
        (
            request.kind.value,
            request.schema_manifest_id,
            *sorted(request.upstream_artifact_ids),
            *sorted(request.upstream_lineage_edge_ids),
            *mappings,
            request.transform_name,
            request.transform_version,
            request.parameters_sha256,
            request.code_commit,
            data_sha256,
            *column_names,
        )
    )
    return f"{request.kind.value}_artifact_{hashlib.sha256(identity.encode()).hexdigest()}"


def artifact_manifest(
    identity: str,
    request: ArtifactWriteRequest,
    data_sha256: str,
    frame: pl.DataFrame,
) -> ArtifactManifest:
    """Create the complete immutable companion manifest for one payload."""
    lineage_digest = hashlib.sha256(f"{identity}|lineage".encode()).hexdigest()
    return ArtifactManifest(
        artifact_id=identity,
        kind=request.kind,
        schema_manifest_id=request.schema_manifest_id,
        upstream_artifact_ids=tuple(sorted(request.upstream_artifact_ids)),
        upstream_lineage_edge_ids=tuple(sorted(request.upstream_lineage_edge_ids)),
        lineage_edge_id=f"lineage_{lineage_digest}",
        field_mappings=tuple(sorted(request.field_mappings, key=lambda item: item.output_field)),
        transform_name=request.transform_name,
        transform_version=request.transform_version,
        parameters_sha256=request.parameters_sha256,
        code_commit=request.code_commit,
        data_sha256=data_sha256,
        row_count=frame.height,
        column_names=tuple(frame.columns),
    )


def artifact_descriptor(directory: Path, manifest: ArtifactManifest) -> ArtifactDescriptor:
    """Build the stable storage reference for a published artifact directory."""
    return ArtifactDescriptor(
        artifact_id=manifest.artifact_id,
        kind=manifest.kind,
        schema_manifest_id=manifest.schema_manifest_id,
        parquet_path=directory / "data.parquet",
        manifest_path=directory / "manifest.json",
        lineage_edge_id=manifest.lineage_edge_id,
        data_sha256=manifest.data_sha256,
        row_count=manifest.row_count,
    )
