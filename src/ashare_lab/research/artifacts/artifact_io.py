"""Byte, schema, and manifest verification for research artifacts."""

import hashlib
from pathlib import Path

import polars as pl
from pydantic import ValidationError

from ashare_lab.research.artifacts.models import (
    ArtifactDescriptor,
    ArtifactManifest,
    ArtifactRule,
    ResearchArtifactError,
)


def load_manifest(path: Path) -> ArtifactManifest:
    """Load one manifest through the frozen Pydantic trust boundary."""
    try:
        with path.open(encoding="utf-8") as manifest_file:
            return ArtifactManifest.model_validate_json(manifest_file.read())
    except (FileNotFoundError, UnicodeDecodeError, ValidationError) as error:
        raise ResearchArtifactError(
            ArtifactRule.INVALID_MANIFEST,
            f"artifact manifest is missing or invalid: {path}",
        ) from error


def file_sha256(path: Path) -> str:
    """Hash a payload without loading it into memory."""
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


def descriptor_matches_manifest(
    descriptor: ArtifactDescriptor,
    manifest: ArtifactManifest,
) -> bool:
    """Confirm that no caller-controlled descriptor field was relabeled."""
    return (
        descriptor.artifact_id == manifest.artifact_id
        and descriptor.kind is manifest.kind
        and descriptor.schema_manifest_id == manifest.schema_manifest_id
        and descriptor.lineage_edge_id == manifest.lineage_edge_id
        and descriptor.data_sha256 == manifest.data_sha256
        and descriptor.row_count == manifest.row_count
    )


def verify_parquet(
    path: Path,
    expected_schema: pl.Schema,
    expected_rows: int,
    expected_sha256: str,
) -> None:
    """Verify immutable bytes, exact schema, and row count."""
    if file_sha256(path) != expected_sha256:
        raise ResearchArtifactError(
            ArtifactRule.CONTENT_MISMATCH,
            f"Parquet digest differs: {path}",
        )
    lazy = pl.scan_parquet(path)
    if lazy.collect_schema() != expected_schema:
        raise ResearchArtifactError(
            ArtifactRule.SCHEMA_MISMATCH,
            f"persisted Parquet schema differs: {path}",
        )
    row_count = lazy.select(pl.len()).collect().item()
    if row_count != expected_rows:
        raise ResearchArtifactError(
            ArtifactRule.CONTENT_MISMATCH,
            f"persisted Parquet row count differs: {path}",
        )
