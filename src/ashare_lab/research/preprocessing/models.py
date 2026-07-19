"""Typed immutable contracts for fold-local preprocessing evidence."""

from datetime import datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenPreprocessingModel(BaseModel):
    """Immutable model suitable for a content-addressed JSON artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FeatureFitStatistics(FrozenPreprocessingModel):
    """Training-only learned values for one model feature."""

    feature_name: str = Field(min_length=1)
    lower_quantile: float = Field(allow_inf_nan=False)
    upper_quantile: float = Field(allow_inf_nan=False)
    fallback_median: float = Field(allow_inf_nan=False)
    neutralization_intercept: float = Field(allow_inf_nan=False)
    neutralization_slope: float = Field(allow_inf_nan=False)


class FoldPreprocessingArtifact(FrozenPreprocessingModel):
    """Complete parameters and scope fitted from exactly one training fold."""

    fold_id: str = Field(min_length=1)
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    transform_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    feature_names: tuple[str, ...] = Field(min_length=1)
    size_feature_name: str = Field(min_length=1)
    training_start: datetime
    training_end: datetime
    training_row_count: int = Field(gt=0)
    training_data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_fallback_median: float = Field(allow_inf_nan=False)
    feature_statistics: tuple[FeatureFitStatistics, ...] = Field(min_length=1)
    industry_neutralization_status: str = Field(pattern=r"^UNAVAILABLE$")
    industry_neutralization_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def fitted_statistics_match_feature_contract(self) -> Self:
        """Reject reordered, duplicated, or temporally invalid fit evidence."""
        statistic_names = tuple(item.feature_name for item in self.feature_statistics)
        if statistic_names != self.feature_names or len(set(self.feature_names)) != len(
            self.feature_names
        ):
            detail = "feature_statistics must match unique feature_names in exact order"
            raise ValueError(detail)
        if self.training_end < self.training_start:
            detail = "training_end cannot precede training_start"
            raise ValueError(detail)
        return self


class FoldPreprocessorDescriptor(FrozenPreprocessingModel):
    """Verified local reference to one immutable preprocessing artifact."""

    artifact_id: str = Field(pattern=r"^preprocessor_artifact_[0-9a-f]{64}$")
    manifest_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
