"""Immutable documents and descriptors used by the model evidence verifier."""

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.datasets.spec_store import DatasetSpecDescriptor
from ashare_lab.research.preprocessing.models import (
    FoldPreprocessingArtifact,
    FoldPreprocessorDescriptor,
)


class FrozenEvidenceModel(BaseModel):
    """Immutable strict document parsed at the artifact boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ContentDocumentDescriptor(FrozenEvidenceModel):
    """Path and exact SHA-256 for one governed JSON document."""

    path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TrainingFieldSchema(FrozenEvidenceModel):
    """Physical and semantic contract for one column in the exact training frame."""

    field_name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool
    unit: str = Field(min_length=1)
    null_semantics: str = Field(min_length=1)
    time_role: str = Field(min_length=1)
    allowed_use: str = Field(min_length=1)
    source_schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]+$")


class TrainingSchemaDocument(FrozenEvidenceModel):
    """Complete ordered model input and target structure."""

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    feature_names: tuple[str, ...] = Field(min_length=1)
    size_feature_name: str = Field(min_length=1)
    label_name: str = Field(min_length=1)
    fields: tuple[TrainingFieldSchema, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def fields_are_unique(self) -> "TrainingSchemaDocument":
        """Reject duplicate physical columns in the frozen training schema."""
        names = tuple(item.field_name for item in self.fields)
        if len(names) != len(set(names)):
            detail = "training schema fields must be unique"
            raise ValueError(detail)
        return self


class TrainingFieldLineage(FrozenEvidenceModel):
    """One training field traced to artifacts and immutable Raw snapshots."""

    field_name: str = Field(min_length=1)
    source_artifact_ids: tuple[str, ...] = Field(min_length=1)
    raw_snapshot_ids: tuple[str, ...] = Field(min_length=1)


class TrainingLineageDocument(FrozenEvidenceModel):
    """Field-level lineage for every feature and label in model order."""

    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]+$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    fields: tuple[TrainingFieldLineage, ...] = Field(min_length=1)


@unique
class ModelPurpose(StrEnum):
    """Permitted destinations for a trained model."""

    RESEARCH_ONLY = "research_only"
    INVESTMENT_DECISION = "investment_decision"


@unique
class TrainingDataKind(StrEnum):
    """Declared artifact provenance with synthetic QA kept non-investable."""

    GOVERNED_REAL = "governed_real"
    SYNTHETIC_QA = "synthetic_qa"


@dataclass(frozen=True, slots=True)
class DevelopmentTrainingEvidence:
    """Actual immutable artifacts required before development fitting."""

    purpose: ModelPurpose
    data_kind: TrainingDataKind
    artifact_root: Path
    dataset_descriptor: DatasetSpecDescriptor
    schema_descriptor: ContentDocumentDescriptor
    lineage_descriptor: ContentDocumentDescriptor
    preprocessor_descriptors: tuple[FoldPreprocessorDescriptor, ...]
    development_data_sha256: str
    holdout_ledger_root: Path
    holdout_spec_id: str


@dataclass(frozen=True, slots=True)
class VerifiedDevelopmentInputs:
    """Parsed artifacts safe to pass from guard to trainer."""

    dataset_spec: DatasetSpec
    preprocessors: tuple[FoldPreprocessingArtifact, ...]


class TrainingEvidenceError(Exception):
    """A training artifact is missing, relabeled, or inconsistent."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: str, detail: str) -> None:
        """Create a typed artifact-verification failure."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the rejected artifact rule and detail."""
        return f"{self.rule}: {self.detail}"
