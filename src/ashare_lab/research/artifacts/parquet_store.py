"""Atomic content-addressed Parquet persistence for research artifacts."""

from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from ashare_lab.research.artifacts.artifact_identity import (
    artifact_descriptor,
    artifact_id,
    artifact_manifest,
)
from ashare_lab.research.artifacts.artifact_io import (
    descriptor_matches_manifest,
    file_sha256,
    load_manifest,
    verify_parquet,
)
from ashare_lab.research.artifacts.models import (
    ArtifactDescriptor,
    ArtifactManifest,
    ArtifactRule,
    ArtifactWriteRequest,
    ResearchArtifactError,
)
from ashare_lab.research.artifacts.schema_registry import ResearchSchemaCatalog


class ParquetArtifactStore:
    """Write immutable payload directories without cross-kind aliasing."""

    def __init__(self, root: Path, schemas: ResearchSchemaCatalog) -> None:
        """Bind the store to one caller-owned artifact root."""
        self._root = root
        self._schemas = schemas

    def write(
        self,
        frame: pl.DataFrame,
        request: ArtifactWriteRequest,
    ) -> ArtifactDescriptor:
        """Persist one frame atomically or verify its existing identity."""
        self._validate_request(frame, request)
        kind_root = self._root / request.kind.value
        kind_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=kind_root) as temporary_name:
            temporary = Path(temporary_name)
            data_path = temporary / "data.parquet"
            frame.write_parquet(data_path, compression="zstd", statistics=True)
            data_sha256 = file_sha256(data_path)
            verify_parquet(data_path, frame.schema, frame.height, data_sha256)
            identity = artifact_id(request, data_sha256, tuple(frame.columns))
            manifest = artifact_manifest(identity, request, data_sha256, frame)
            manifest_path = temporary / "manifest.json"
            with manifest_path.open("w", encoding="utf-8") as manifest_file:
                manifest_file.write(manifest.model_dump_json(indent=2))
                manifest_file.write("\n")
            final_directory = kind_root / identity
            descriptor = artifact_descriptor(final_directory, manifest)
            if final_directory.exists():
                self._verify_existing(descriptor, manifest)
                return descriptor
            temporary.replace(final_directory)
            return descriptor

    def read(self, descriptor: ArtifactDescriptor) -> pl.DataFrame:
        """Read a payload only after verifying its immutable bytes."""
        self._verify_descriptor_boundary(descriptor)
        manifest = load_manifest(descriptor.manifest_path)
        self._verify_existing(descriptor, manifest)
        frame = pl.read_parquet(descriptor.parquet_path)
        self._schemas.validate(descriptor.kind, frame, descriptor.schema_manifest_id)
        return frame

    def _verify_existing(
        self,
        descriptor: ArtifactDescriptor,
        expected_manifest: ArtifactManifest,
    ) -> None:
        actual_manifest = load_manifest(descriptor.manifest_path)
        if actual_manifest != expected_manifest:
            raise ResearchArtifactError(
                ArtifactRule.CONTENT_MISMATCH,
                f"manifest differs for {descriptor.artifact_id}",
            )
        if not descriptor_matches_manifest(descriptor, actual_manifest):
            raise ResearchArtifactError(
                ArtifactRule.CONTENT_MISMATCH,
                f"descriptor differs from manifest for {descriptor.artifact_id}",
            )
        actual_sha256 = file_sha256(descriptor.parquet_path)
        if actual_sha256 != descriptor.data_sha256:
            raise ResearchArtifactError(
                ArtifactRule.CONTENT_MISMATCH,
                f"Parquet bytes differ for {descriptor.artifact_id}",
            )
        verify_parquet(
            descriptor.parquet_path,
            self._schemas.polars_schema(descriptor.kind),
            descriptor.row_count,
            descriptor.data_sha256,
        )

    def _validate_request(
        self,
        frame: pl.DataFrame,
        request: ArtifactWriteRequest,
    ) -> None:
        self._schemas.validate(request.kind, frame, request.schema_manifest_id)
        if not request.upstream_lineage_edge_ids or not request.field_mappings:
            raise ResearchArtifactError(
                ArtifactRule.MISSING_LINEAGE,
                "artifact must reference lineage edges and field mappings",
            )
        outputs = tuple(mapping.output_field for mapping in request.field_mappings)
        upstreams = set(request.upstream_artifact_ids)
        if len(outputs) != len(set(outputs)) or set(outputs) != set(frame.columns):
            raise ResearchArtifactError(
                ArtifactRule.MISSING_LINEAGE,
                "field mappings must cover every output column exactly once",
            )
        if any(mapping.upstream_artifact_id not in upstreams for mapping in request.field_mappings):
            raise ResearchArtifactError(
                ArtifactRule.MISSING_LINEAGE,
                "field mapping references an undeclared upstream artifact",
            )

    def _verify_descriptor_boundary(self, descriptor: ArtifactDescriptor) -> None:
        directory = self._root / descriptor.kind.value / descriptor.artifact_id
        if (
            descriptor.parquet_path != directory / "data.parquet"
            or descriptor.manifest_path != directory / "manifest.json"
        ):
            raise ResearchArtifactError(
                ArtifactRule.CONTENT_MISMATCH,
                f"descriptor crosses its physical kind boundary: {descriptor.artifact_id}",
            )
