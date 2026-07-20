"""Versioned lineage for one model-training experiment."""

from enum import StrEnum, unique
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


@unique
class ModelFamily(StrEnum):
    """Closed model families permitted by governed experiments."""

    RIDGE = "ridge"
    LIGHTGBM_RANKER = "lightgbm_ranker"


class ExperimentManifest(BaseModel):
    """Minimum reproducibility evidence persisted for every training run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    training_run_id: str = Field(min_length=1)
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]+$")
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]+$")
    rulebook_version: str = Field(min_length=1)
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    model_family: ModelFamily
    feature_names: tuple[str, ...] = Field(min_length=1)
    size_feature_name: str = Field(min_length=1)
    label_name: str = Field(min_length=1)
    split_protocol: str = Field(min_length=1)
    random_seed: int
    final_test_runs: int = Field(default=0, ge=0, le=1)
    ridge_alphas: tuple[float, ...] = ()
    preprocessor_artifact_ids: tuple[str, ...] = ()
    trial_batch_id: str = Field(min_length=1)
    factor_report_id: str = Field(pattern=r"^factor_report_[0-9a-f]{64}$")
    portfolio_backtest_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    portfolio_rule_version: str = Field(min_length=1)
    cost_rule_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def ridge_protocol_is_frozen(self) -> Self:
        """Require the predeclared Ridge grid and exact preprocessing identities."""
        match self.model_family:
            case ModelFamily.RIDGE:
                if self.ridge_alphas != (0.1, 1.0, 10.0, 100.0):
                    detail = "Ridge alpha grid must equal the frozen protocol"
                    raise ValueError(detail)
                if not self.preprocessor_artifact_ids:
                    detail = "Ridge experiments require preprocessor artifact identities"
                    raise ValueError(detail)
            case ModelFamily.LIGHTGBM_RANKER:
                if self.ridge_alphas:
                    detail = "non-Ridge experiments cannot declare Ridge alphas"
                    raise ValueError(detail)
        return self
