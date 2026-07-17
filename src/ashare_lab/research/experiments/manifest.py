"""Versioned lineage for one model-training experiment."""

from enum import StrEnum, unique

from pydantic import BaseModel, ConfigDict, Field


@unique
class ModelFamily(StrEnum):
    """Closed model families permitted by governed experiments."""

    RIDGE = "ridge"
    LIGHTGBM_RANKER = "lightgbm_ranker"


class ExperimentManifest(BaseModel):
    """Minimum reproducibility evidence persisted for every training run."""

    model_config = ConfigDict(frozen=True)

    training_run_id: str = Field(min_length=1)
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]+$")
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]+$")
    rulebook_version: str = Field(min_length=1)
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    model_family: ModelFamily
    feature_names: tuple[str, ...] = Field(min_length=1)
    label_name: str = Field(min_length=1)
    split_protocol: str = Field(min_length=1)
    random_seed: int
    final_test_runs: int = Field(default=0, ge=0, le=1)
