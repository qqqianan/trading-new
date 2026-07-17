"""Closed contracts for immutable research artifacts."""

from enum import StrEnum, unique
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


@unique
class ArtifactKind(StrEnum):
    """Physically isolated research artifact families."""

    FEATURE = "feature"
    LABEL = "label"
    UNIVERSE = "universe"
    DATASET = "dataset"
    PREPROCESSOR = "preprocessor"
    PREDICTION = "prediction"


class ArtifactWriteRequest(BaseModel):
    """Material transformation evidence bound into an artifact identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ArtifactKind
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]+$")
    upstream_artifact_ids: tuple[str, ...] = Field(min_length=1)
    upstream_lineage_edge_ids: tuple[str, ...]
    field_mappings: tuple["ArtifactFieldMapping", ...]
    transform_name: str = Field(min_length=1)
    transform_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


class ArtifactManifest(BaseModel):
    """Machine-readable immutable companion to one Parquet payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    kind: ArtifactKind
    schema_manifest_id: str
    upstream_artifact_ids: tuple[str, ...]
    upstream_lineage_edge_ids: tuple[str, ...]
    lineage_edge_id: str
    field_mappings: tuple["ArtifactFieldMapping", ...]
    transform_name: str
    transform_version: str
    parameters_sha256: str
    code_commit: str
    data_sha256: str
    row_count: int = Field(ge=0)
    column_names: tuple[str, ...]


class ArtifactDescriptor(BaseModel):
    """Stable storage reference passed to datasets and model adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    kind: ArtifactKind
    schema_manifest_id: str
    parquet_path: Path
    manifest_path: Path
    lineage_edge_id: str
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=0)


@unique
class ArtifactRule(StrEnum):
    """Stable failure codes for research artifact persistence."""

    MISSING_LINEAGE = "missing_lineage"
    CONTENT_MISMATCH = "content_mismatch"
    INVALID_MANIFEST = "invalid_manifest"
    INVALID_SCHEMA = "invalid_schema"
    SCHEMA_MISMATCH = "schema_mismatch"


class ResearchArtifactError(Exception):
    """An artifact violates immutability or lineage requirements."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: ArtifactRule, detail: str) -> None:
        """Create a typed artifact rejection."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable rule and concrete failure detail."""
        return f"{self.rule.value}: {self.detail}"


class ArtifactFieldMapping(BaseModel):
    """One output column traced to an upstream artifact field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_field: str = Field(min_length=1)
    upstream_artifact_id: str = Field(min_length=1)
    upstream_field: str = Field(min_length=1)
    transformation: str = Field(min_length=1)
