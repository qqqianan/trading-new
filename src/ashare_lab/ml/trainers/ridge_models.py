"""Immutable Ridge selection, model, and prediction artifact contracts."""

from pydantic import BaseModel, ConfigDict, Field


class FrozenRidgeModel(BaseModel):
    """Strict immutable model artifact boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RidgeCandidateResult(FrozenRidgeModel):
    """Validation loss for one predeclared alpha across every fold."""

    alpha: float = Field(gt=0, allow_inf_nan=False)
    fold_validation_mse: tuple[float, ...] = Field(min_length=1)
    mean_validation_mse: float = Field(ge=0, allow_inf_nan=False)


class RidgeFoldResult(FrozenRidgeModel):
    """Baseline, selected Ridge, and internal-test result for one fold."""

    fold_index: int = Field(ge=0)
    baseline_validation_mse: float = Field(ge=0, allow_inf_nan=False)
    selected_validation_mse: float = Field(ge=0, allow_inf_nan=False)
    internal_test_mse: float = Field(ge=0, allow_inf_nan=False)
    internal_test_rows: int = Field(gt=0)


class FoldPredictionBatch(FrozenRidgeModel):
    """Internal development-test predictions bound to ordered observation keys."""

    fold_index: int = Field(ge=0)
    observation_keys_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predictions: tuple[float, ...] = Field(min_length=1)
    labels: tuple[float, ...] = Field(min_length=1)


class RidgePredictionArtifact(FrozenRidgeModel):
    """Selected-alpha internal test predictions, never final holdout rows."""

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    training_run_id: str = Field(min_length=1)
    batches: tuple[FoldPredictionBatch, ...] = Field(min_length=1)


class RidgeArtifactPayload(FrozenRidgeModel):
    """Content determining one Ridge model identity."""

    training_run_id: str = Field(min_length=1)
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]+$")
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]+$")
    experiment_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_alpha: float = Field(gt=0, allow_inf_nan=False)
    candidate_results: tuple[RidgeCandidateResult, ...] = Field(min_length=1)
    fold_results: tuple[RidgeFoldResult, ...] = Field(min_length=1)
    baseline_mean_validation_mse: float = Field(ge=0, allow_inf_nan=False)
    internal_test_mean_mse: float = Field(ge=0, allow_inf_nan=False)
    model_feature_names: tuple[str, ...] = Field(min_length=1)
    coefficients: tuple[float, ...] = Field(min_length=1)
    intercept: float = Field(allow_inf_nan=False)
    preprocessor_artifact_ids: tuple[str, ...] = Field(min_length=1)
    prediction_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prediction_lineage_id: str = Field(pattern=r"^prediction_lineage_[0-9a-f]{64}$")
    prediction_row_count: int = Field(gt=0)
    random_seed: int
    portfolio_rule_version: str = Field(min_length=1)
    cost_rule_version: str = Field(min_length=1)
    final_test_runs: int = Field(ge=0, le=0)
    model_status: str = Field(pattern=r"^DRAFT$")


class RidgeExperimentArtifact(RidgeArtifactPayload):
    """Stored Ridge payload with its content-addressed model ID."""

    model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
