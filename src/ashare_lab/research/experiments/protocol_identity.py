"""Deterministic identity factory for preregistered model experiments."""

import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.research.experiments.protocol_models import (
    DevelopmentPromotionGates,
    FinalHoldoutPolicy,
    ModelExperimentProtocol,
    ModelExperimentProtocolPayload,
)


class ModelProtocolRequest(BaseModel):
    """Verified identities and owner inputs used to freeze one protocol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]{64}$")
    parent_model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
    parent_diagnostic_report_id: str = Field(pattern=r"^model_diagnostic_[0-9a-f]{64}$")
    registered_at: datetime
    registered_by: str = Field(min_length=1)
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    rulebook_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    feature_names: tuple[str, ...] = Field(min_length=1)
    label_name: str = Field(min_length=1)
    cost_rule_version: str = Field(min_length=1)
    risk_rule_version: str = Field(min_length=1)
    holdout_spec_id: str = Field(pattern=r"^holdout_spec_[0-9a-f]{64}$")


def create_rank_aligned_protocol(request: ModelProtocolRequest) -> ModelExperimentProtocol:
    """Freeze the next interpretable rank-aligned experiment before implementation."""
    payload = ModelExperimentProtocolPayload(
        dataset_snapshot_id=request.dataset_snapshot_id,
        schema_manifest_id=request.schema_manifest_id,
        lineage_manifest_id=request.lineage_manifest_id,
        parent_model_id=request.parent_model_id,
        parent_diagnostic_report_id=request.parent_diagnostic_report_id,
        registered_at=request.registered_at,
        registered_by=request.registered_by,
        code_commit=request.code_commit,
        rulebook_version=request.rulebook_version,
        experiment_name="ridge_rank_alignment_v1",
        hypothesis=(
            "Cross-sectional rank-label Ridge may align linear predictions with Top30 selection "
            "better than return-MSE Ridge while preserving fold-level interpretability."
        ),
        candidate_model_family="ridge_rank",
        training_objective="ridge_mse_on_cross_sectional_rank_label",
        feature_names=request.feature_names,
        label_name=request.label_name,
        label_transform="cross_sectional_percentile_rank",
        split_protocol="purged_walk_forward_medium_horizon_v1",
        preprocessing_version="1.0.0",
        portfolio_rule_version="2.0.0",
        cost_rule_version=request.cost_rule_version,
        risk_rule_version=request.risk_rule_version,
        evidence_classification="POST_HOC_DERIVED_NEW_EXPERIMENT",
        development_end=date(2024, 12, 31),
        promotion_gates=DevelopmentPromotionGates(
            minimum_mean_rank_ic=0.0,
            minimum_fold_rank_ic=0.0,
            minimum_direction_consistency=0.55,
            require_baseline_total_return_outperformance=True,
            require_baseline_sharpe_outperformance=True,
            forbid_risk_halt=True,
            require_complete_industry_pit=True,
        ),
        final_holdout=FinalHoldoutPolicy(
            holdout_spec_id=request.holdout_spec_id,
            holdout_start=date(2025, 1, 1),
            maximum_accesses=1,
            requires_all_development_gates=True,
            requires_manual_authorization=True,
        ),
        status="PREREGISTERED_NOT_IMPLEMENTED",
    )
    content = payload.model_dump(mode="json")
    identity = hashlib.sha256(
        json.dumps(content, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return ModelExperimentProtocol.model_validate(
        {"protocol_id": f"model_protocol_{identity}", **content}
    )


def validate_model_protocol(protocol: ModelExperimentProtocol) -> None:
    """Recompute a stored protocol identity from its immutable registration inputs."""
    request = ModelProtocolRequest(
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        schema_manifest_id=protocol.schema_manifest_id,
        lineage_manifest_id=protocol.lineage_manifest_id,
        parent_model_id=protocol.parent_model_id,
        parent_diagnostic_report_id=protocol.parent_diagnostic_report_id,
        registered_at=protocol.registered_at,
        registered_by=protocol.registered_by,
        code_commit=protocol.code_commit,
        rulebook_version=protocol.rulebook_version,
        feature_names=protocol.feature_names,
        label_name=protocol.label_name,
        cost_rule_version=protocol.cost_rule_version,
        risk_rule_version=protocol.risk_rule_version,
        holdout_spec_id=protocol.final_holdout.holdout_spec_id,
    )
    if create_rank_aligned_protocol(request) != protocol:
        detail = "model experiment protocol identity differs from registered content"
        raise ModelProtocolIdentityError(detail)


class ModelProtocolIdentityError(Exception):
    """A caller-controlled protocol identity differs from its content."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable identity failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the identity boundary and concrete blocker."""
        return f"model_protocol_identity: {self.detail}"
