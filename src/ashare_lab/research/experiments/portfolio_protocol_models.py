"""Immutable preregistration contract for a portfolio-rule experiment."""

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenPortfolioProtocolModel(BaseModel):
    """Strict immutable boundary for portfolio experiment preregistration."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FactorAnchorVetoRule(FrozenPortfolioProtocolModel):
    """Fixed factor-primary selection with a non-optimized Ridge veto."""

    primary_signal: Literal["accepted_factor_baseline_equal_composite_v1"]
    veto_signal: Literal["ridge_rank_model_score"]
    veto_quantile: float = Field(ge=0.2, le=0.2, allow_inf_nan=False)
    selection_order: Literal["factor_score_desc_symbol_asc"]
    maximum_positions: Literal[30]
    target_gross_weight: float = Field(ge=0.95, le=0.95, allow_inf_nan=False)
    cash_weight: float = Field(ge=0.05, le=0.05, allow_inf_nan=False)
    insufficient_survivors: Literal["FAIL_CLOSED"]


class PortfolioPromotionGates(FrozenPortfolioProtocolModel):
    """Frozen gates for later fresh-forward candidate evaluation."""

    require_baseline_total_return_outperformance: Literal[True]
    require_baseline_sharpe_outperformance: Literal[True]
    require_nonnegative_excess_return: Literal[True]
    forbid_risk_halt: Literal[True]
    require_complete_industry_pit: Literal[True]


class FreshForwardPolicy(FrozenPortfolioProtocolModel):
    """Evidence that must arrive strictly after preregistration."""

    start_date: date
    minimum_decision_dates: Literal[26]
    label_maturity_trading_days: Literal[20]
    final_holdout_access_permitted: Literal[False]


class PortfolioExperimentProtocolPayload(FrozenPortfolioProtocolModel):
    """All preregistered portfolio experiment content except derived identity."""

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]{64}$")
    parent_attribution_report_id: str = Field(pattern=r"^model_attribution_[0-9a-f]{64}$")
    parent_diagnostic_report_id: str = Field(pattern=r"^model_diagnostic_[0-9a-f]{64}$")
    parent_model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
    prediction_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_target_artifact_id: str = Field(pattern=r"^portfolio_targets_[0-9a-f]{64}$")
    baseline_backtest_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    model_target_artifact_id: str = Field(pattern=r"^portfolio_targets_[0-9a-f]{64}$")
    model_backtest_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    registered_at: datetime
    registered_by: str = Field(min_length=1)
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    rulebook_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    experiment_name: Literal["factor_anchor_ridge_bottom_quintile_veto_v1"]
    hypothesis: str = Field(min_length=20)
    candidate_rule: FactorAnchorVetoRule
    cost_rule_version: str = Field(min_length=1)
    risk_rule_version: str = Field(min_length=1)
    evidence_classification: Literal["REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE"]
    reused_development_end: date
    promotion_gates: PortfolioPromotionGates
    fresh_forward: FreshForwardPolicy
    status: Literal["PREREGISTERED_NOT_IMPLEMENTED"]

    @field_validator("registered_at")
    @classmethod
    def registered_at_has_timezone(cls, value: datetime) -> datetime:
        """Reject ambiguous registration times before content hashing."""
        if value.tzinfo is None or value.utcoffset() is None:
            detail = "registration time must be timezone-aware"
            raise ValueError(detail)
        return value

    @model_validator(mode="after")
    def evidence_clocks_are_ordered(self) -> Self:
        """Ensure fresh evidence cannot be backdated into seen development data."""
        if self.reused_development_end >= self.fresh_forward.start_date:
            detail = "fresh-forward start must follow reused development evidence"
            raise ValueError(detail)
        if self.registered_at.date() >= self.fresh_forward.start_date:
            detail = "fresh-forward start must follow protocol registration"
            raise ValueError(detail)
        return self


class PortfolioExperimentProtocol(PortfolioExperimentProtocolPayload):
    """Content-addressed protocol fixed before candidate implementation."""

    protocol_id: str = Field(pattern=r"^portfolio_protocol_[0-9a-f]{64}$")
