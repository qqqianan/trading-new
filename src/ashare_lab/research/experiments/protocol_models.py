"""Immutable preregistration contract for post-hoc-derived model experiments."""

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenExperimentProtocolModel(BaseModel):
    """Strict immutable boundary for experiment preregistration."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DevelopmentPromotionGates(FrozenExperimentProtocolModel):
    """Thresholds fixed before the candidate trainer is implemented."""

    minimum_mean_rank_ic: float = Field(ge=0, le=1, allow_inf_nan=False)
    minimum_fold_rank_ic: float = Field(ge=0, le=1, allow_inf_nan=False)
    minimum_direction_consistency: float = Field(ge=0, le=1, allow_inf_nan=False)
    require_baseline_total_return_outperformance: Literal[True]
    require_baseline_sharpe_outperformance: Literal[True]
    forbid_risk_halt: Literal[True]
    require_complete_industry_pit: Literal[True]


class FinalHoldoutPolicy(FrozenExperimentProtocolModel):
    """Single-use sealed evaluation conditions for a frozen candidate."""

    holdout_spec_id: str = Field(pattern=r"^holdout_spec_[0-9a-f]{64}$")
    holdout_start: date
    maximum_accesses: Literal[1]
    requires_all_development_gates: Literal[True]
    requires_manual_authorization: Literal[True]


class ModelExperimentProtocolPayload(FrozenExperimentProtocolModel):
    """All preregistered experiment content except its derived identity."""

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]{64}$")
    parent_model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
    parent_diagnostic_report_id: str = Field(pattern=r"^model_diagnostic_[0-9a-f]{64}$")
    registered_at: datetime
    registered_by: str = Field(min_length=1)
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    rulebook_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    experiment_name: Literal["ridge_rank_alignment_v1"]
    hypothesis: str = Field(min_length=20)
    candidate_model_family: Literal["ridge_rank"]
    training_objective: Literal["ridge_mse_on_cross_sectional_rank_label"]
    feature_names: tuple[str, ...] = Field(min_length=1)
    label_name: str = Field(min_length=1)
    label_transform: Literal["cross_sectional_percentile_rank"]
    split_protocol: Literal["purged_walk_forward_medium_horizon_v1"]
    preprocessing_version: Literal["1.0.0"]
    portfolio_rule_version: Literal["2.0.0"]
    cost_rule_version: str = Field(min_length=1)
    risk_rule_version: str = Field(min_length=1)
    evidence_classification: Literal["POST_HOC_DERIVED_NEW_EXPERIMENT"]
    development_end: date
    promotion_gates: DevelopmentPromotionGates
    final_holdout: FinalHoldoutPolicy
    status: Literal["PREREGISTERED_NOT_IMPLEMENTED"]

    @field_validator("registered_at")
    @classmethod
    def registered_at_has_timezone(cls, value: datetime) -> datetime:
        """Reject ambiguous registration times before protocol content is hashed."""
        if value.tzinfo is None or value.utcoffset() is None:
            detail = "registration time must be timezone-aware"
            raise ValueError(detail)
        return value

    @model_validator(mode="after")
    def dates_and_features_are_consistent(self) -> Self:
        """Reject overlapping holdout dates and duplicate feature contracts."""
        if self.final_holdout.holdout_start <= self.development_end:
            detail = "final holdout must start after development"
            raise ValueError(detail)
        if len(self.feature_names) != len(set(self.feature_names)):
            detail = "protocol feature names must be unique"
            raise ValueError(detail)
        return self


class ModelExperimentProtocol(ModelExperimentProtocolPayload):
    """Content-addressed protocol fixed before rank-aligned model implementation."""

    protocol_id: str = Field(pattern=r"^model_protocol_[0-9a-f]{64}$")
