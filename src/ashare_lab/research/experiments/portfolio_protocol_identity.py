"""Deterministic identity for the factor-anchor Ridge-veto experiment."""

import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.research.experiments.portfolio_protocol_models import (
    FactorAnchorVetoRule,
    FreshForwardPolicy,
    PortfolioExperimentProtocol,
    PortfolioExperimentProtocolPayload,
    PortfolioPromotionGates,
)

FRESH_FORWARD_START = date(2026, 7, 24)


class PortfolioProtocolRequest(BaseModel):
    """Verified identities and owner inputs used to freeze one protocol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    cost_rule_version: str = Field(min_length=1)
    risk_rule_version: str = Field(min_length=1)


def create_factor_anchor_veto_protocol(
    request: PortfolioProtocolRequest,
) -> PortfolioExperimentProtocol:
    """Freeze one interpretable portfolio hypothesis before implementation."""
    payload = PortfolioExperimentProtocolPayload(
        **request.model_dump(),
        experiment_name="factor_anchor_ridge_bottom_quintile_veto_v1",
        hypothesis=(
            "Keeping the accepted factor composite as the primary rank while excluding the "
            "bottom Ridge score quintile may preserve baseline upside and use Ridge only for "
            "its observed downside-avoidance behavior."
        ),
        candidate_rule=FactorAnchorVetoRule(
            primary_signal="accepted_factor_baseline_equal_composite_v1",
            veto_signal="ridge_rank_model_score",
            veto_quantile=0.2,
            selection_order="factor_score_desc_symbol_asc",
            maximum_positions=30,
            target_gross_weight=0.95,
            cash_weight=0.05,
            insufficient_survivors="FAIL_CLOSED",
        ),
        evidence_classification="REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE",
        reused_development_end=date(2024, 12, 31),
        promotion_gates=PortfolioPromotionGates(
            require_baseline_total_return_outperformance=True,
            require_baseline_sharpe_outperformance=True,
            require_nonnegative_excess_return=True,
            forbid_risk_halt=True,
            require_complete_industry_pit=True,
        ),
        fresh_forward=FreshForwardPolicy(
            start_date=FRESH_FORWARD_START,
            minimum_decision_dates=26,
            label_maturity_trading_days=20,
            final_holdout_access_permitted=False,
        ),
        status="PREREGISTERED_NOT_IMPLEMENTED",
    )
    content = payload.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(content, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return PortfolioExperimentProtocol.model_validate(
        {"protocol_id": f"portfolio_protocol_{digest}", **content}
    )


def validate_portfolio_protocol(protocol: PortfolioExperimentProtocol) -> None:
    """Recompute a stored protocol identity from immutable registration inputs."""
    request = PortfolioProtocolRequest.model_validate(
        protocol.model_dump(include=set(PortfolioProtocolRequest.model_fields))
    )
    if create_factor_anchor_veto_protocol(request) != protocol:
        detail = "portfolio protocol identity differs from registered content"
        raise PortfolioProtocolIdentityError(detail)


class PortfolioProtocolIdentityError(Exception):
    """A protocol identity differs from its immutable content."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable identity failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the identity boundary and concrete blocker."""
        return f"portfolio_protocol_identity: {self.detail}"
