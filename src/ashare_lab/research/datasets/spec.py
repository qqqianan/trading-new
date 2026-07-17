"""Content-addressed research dataset specification."""

import hashlib
import json
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class FrozenArtifactModel(BaseModel):
    """Immutable model for research artifacts crossing file boundaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FeatureRef(FrozenArtifactModel):
    """Pinned feature name and implementation version."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class LabelRef(FrozenArtifactModel):
    """Pinned label definition used to prevent silent target changes."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class DatasetSpec(FrozenArtifactModel):
    """Complete logical inputs that determine one dataset identity."""

    rulebook_version: str = Field(min_length=1)
    coverage_report_id: str = Field(pattern=r"^coverage_[0-9a-f]+$")
    input_manifest_id: str = Field(pattern=r"^inputs_[0-9a-f]+$")
    source_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]+$")
    input_schema_manifest_ids: tuple[str, ...] = Field(min_length=1)
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]+$")
    feature_artifact_ids: tuple[str, ...] = Field(min_length=1)
    feature_lineage_edge_ids: tuple[str, ...] = Field(min_length=1)
    label_artifact_id: str = Field(min_length=1)
    label_lineage_edge_ids: tuple[str, ...] = Field(min_length=1)
    universe_version: str = Field(min_length=1)
    features: tuple[FeatureRef, ...] = Field(min_length=1)
    label: LabelRef
    start_date: date
    end_date: date

    @property
    def snapshot_id(self) -> str:
        """Return a deterministic identity for every material dataset input."""
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        digest = hashlib.sha256(payload).hexdigest()[:20]
        return f"ds_{digest}"
