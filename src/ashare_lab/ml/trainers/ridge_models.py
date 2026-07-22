"""Immutable Ridge selection, model, and prediction artifact contracts."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.research.experiments.manifest import LabelTransform, ModelFamily


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
    coefficients: tuple[float, ...] = ()
    intercept: float | None = Field(default=None, allow_inf_nan=False)


class FoldPredictionBatch(FrozenRidgeModel):
    """Internal development-test predictions bound to ordered observation keys."""

    fold_index: int = Field(ge=0)
    observation_keys_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predictions: tuple[float, ...] = Field(min_length=1)
    labels: tuple[float, ...] = Field(min_length=1)
    decision_times: tuple[datetime, ...] = ()
    symbols: tuple[str, ...] = ()

    @model_validator(mode="after")
    def row_vectors_are_aligned(self) -> Self:
        """Require aligned values while preserving readability of legacy hash-only batches."""
        if len(self.predictions) != len(self.labels):
            detail = "prediction and label rows differ"
            raise ValueError(detail)
        if (self.decision_times or self.symbols) and not (
            len(self.decision_times) == len(self.symbols) == len(self.predictions)
        ):
            detail = "prediction observation keys are incomplete"
            raise ValueError(detail)
        return self


class RidgePredictionArtifact(FrozenRidgeModel):
    """Selected-alpha internal test predictions, never final holdout rows."""

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    training_run_id: str = Field(min_length=1)
    batches: tuple[FoldPredictionBatch, ...] = Field(min_length=1)
    label_semantics: Literal["raw_forward_return_for_diagnostics"] = (
        "raw_forward_return_for_diagnostics"
    )


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
    training_feature_names: tuple[str, ...] = ()
    model_feature_names: tuple[str, ...] = Field(min_length=1)
    coefficients: tuple[float, ...] = Field(min_length=1)
    intercept: float = Field(allow_inf_nan=False)
    preprocessor_artifact_ids: tuple[str, ...] = Field(min_length=1)
    prediction_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prediction_lineage_id: str = Field(pattern=r"^prediction_lineage_[0-9a-f]{64}$")
    prediction_row_count: int = Field(gt=0)
    factor_report_id: str | None = Field(default=None, pattern=r"^factor_report_[0-9a-f]{64}$")
    trial_batch_id: str | None = Field(default=None, pattern=r"^trial_batch_[0-9a-f]{64}$")
    source_portfolio_backtest_id: str | None = Field(
        default=None,
        pattern=r"^portfolio_backtest_[0-9a-f]{64}$",
    )
    random_seed: int
    portfolio_rule_version: str = Field(min_length=1)
    cost_rule_version: str = Field(min_length=1)
    model_family: ModelFamily = ModelFamily.RIDGE
    label_transform: LabelTransform = LabelTransform.IDENTITY
    experiment_protocol_id: str | None = Field(
        default=None,
        pattern=r"^model_protocol_[0-9a-f]{64}$",
    )
    prediction_label_semantics: Literal["raw_forward_return_for_diagnostics"] = (
        "raw_forward_return_for_diagnostics"
    )
    final_test_runs: int = Field(ge=0, le=0)
    model_status: str = Field(pattern=r"^DRAFT$")

    @model_validator(mode="after")
    def objective_and_protocol_are_consistent(self) -> Self:
        """Reject model manifests that relabel return and rank objectives."""
        if self.model_family is ModelFamily.RIDGE_RANK and (
            self.label_transform is not LabelTransform.CROSS_SECTIONAL_PERCENTILE_RANK
            or self.experiment_protocol_id is None
        ):
            detail = "rank Ridge artifact requires its protocol and rank label transform"
            raise ValueError(detail)
        if self.model_family is ModelFamily.RIDGE and (
            self.label_transform is not LabelTransform.IDENTITY
            or self.experiment_protocol_id is not None
        ):
            detail = "return Ridge artifact cannot declare rank protocol semantics"
            raise ValueError(detail)
        return self


class RidgeExperimentArtifact(RidgeArtifactPayload):
    """Stored Ridge payload with its content-addressed model ID."""

    model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
