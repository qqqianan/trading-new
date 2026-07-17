"""Atomic content-addressed Parquet persistence for research artifacts."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
from pydantic import ValidationError

from ashare_lab.research.artifacts.models import (
    ArtifactDescriptor,
    ArtifactManifest,
    ArtifactRule,
    ArtifactWriteRequest,
    ResearchArtifactError,
)


class ParquetArtifactStore:
    """Write immutable payload directories without cross-kind aliasing."""

    def __init__(self, root: Path) -> None:
        """Bind the store to one caller-owned artifact root."""
        self._root = root

    def write(
        self,
        frame: pl.DataFrame,
        request: ArtifactWriteRequest,
    ) -> ArtifactDescriptor:
        """Persist one frame atomically or verify its existing identity."""
        if not request.upstream_lineage_edge_ids or not request.field_mappings:
            raise ResearchArtifactError(
                ArtifactRule.MISSING_LINEAGE,
                "artifact must reference at least one lineage edge",
            )
        kind_root = self._root / request.kind.value
        kind_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=kind_root) as temporary_name:
            temporary = Path(temporary_name)
            data_path = temporary / "data.parquet"
            frame.write_parquet(data_path, compression="zstd", statistics=True)
            data_sha256 = _file_sha256(data_path)
            artifact_id = _artifact_id(request, data_sha256, tuple(frame.columns))
            manifest = _manifest(artifact_id, request, data_sha256, frame)
            manifest_path = temporary / "manifest.json"
            with manifest_path.open("w", encoding="utf-8") as manifest_file:
                manifest_file.write(manifest.model_dump_json(indent=2))
                manifest_file.write("\n")
            final_directory = kind_root / artifact_id
            descriptor = _descriptor(final_directory, manifest)
            if final_directory.exists():
                self._verify_existing(descriptor, manifest)
                return descriptor
            temporary.replace(final_directory)
            return descriptor

    def read(self, descriptor: ArtifactDescriptor) -> pl.DataFrame:
        """Read a payload only after verifying its immutable bytes."""
        manifest = _load_manifest(descriptor.manifest_path)
        self._verify_existing(descriptor, manifest)
        return pl.read_parquet(descriptor.parquet_path)

    @staticmethod
    def _verify_existing(
        descriptor: ArtifactDescriptor,
        expected_manifest: ArtifactManifest,
    ) -> None:
        actual_manifest = _load_manifest(descriptor.manifest_path)
        if actual_manifest != expected_manifest:
            raise ResearchArtifactError(
                ArtifactRule.CONTENT_MISMATCH,
                f"manifest differs for {descriptor.artifact_id}",
            )
        actual_sha256 = _file_sha256(descriptor.parquet_path)
        if actual_sha256 != descriptor.data_sha256:
            raise ResearchArtifactError(
                ArtifactRule.CONTENT_MISMATCH,
                f"Parquet bytes differ for {descriptor.artifact_id}",
            )


def _artifact_id(
    request: ArtifactWriteRequest,
    data_sha256: str,
    column_names: tuple[str, ...],
) -> str:
    identity = "|".join(
        (
            request.kind.value,
            request.schema_manifest_id,
            *sorted(request.upstream_artifact_ids),
            *sorted(request.upstream_lineage_edge_ids),
            *sorted(request.field_mappings),
            request.transform_name,
            request.transform_version,
            request.parameters_sha256,
            request.code_commit,
            data_sha256,
            *column_names,
        )
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"{request.kind.value}_artifact_{digest}"


def _manifest(
    artifact_id: str,
    request: ArtifactWriteRequest,
    data_sha256: str,
    frame: pl.DataFrame,
) -> ArtifactManifest:
    lineage_digest = hashlib.sha256(f"{artifact_id}|lineage".encode()).hexdigest()
    return ArtifactManifest(
        artifact_id=artifact_id,
        kind=request.kind,
        schema_manifest_id=request.schema_manifest_id,
        upstream_artifact_ids=tuple(sorted(request.upstream_artifact_ids)),
        upstream_lineage_edge_ids=tuple(sorted(request.upstream_lineage_edge_ids)),
        lineage_edge_id=f"lineage_{lineage_digest}",
        field_mappings=tuple(sorted(request.field_mappings)),
        transform_name=request.transform_name,
        transform_version=request.transform_version,
        parameters_sha256=request.parameters_sha256,
        code_commit=request.code_commit,
        data_sha256=data_sha256,
        row_count=frame.height,
        column_names=tuple(frame.columns),
    )


def _descriptor(directory: Path, manifest: ArtifactManifest) -> ArtifactDescriptor:
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


def _load_manifest(path: Path) -> ArtifactManifest:
    try:
        with path.open(encoding="utf-8") as manifest_file:
            return ArtifactManifest.model_validate_json(manifest_file.read())
    except (FileNotFoundError, ValidationError) as error:
        raise ResearchArtifactError(
            ArtifactRule.INVALID_MANIFEST,
            f"artifact manifest is missing or invalid: {path}",
        ) from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as artifact_file:
            for block in iter(lambda: artifact_file.read(1024 * 1024), b""):
                digest.update(block)
    except FileNotFoundError as error:
        raise ResearchArtifactError(
            ArtifactRule.CONTENT_MISMATCH,
            f"artifact payload is missing: {path}",
        ) from error
    return digest.hexdigest()
