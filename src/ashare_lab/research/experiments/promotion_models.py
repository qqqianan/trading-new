"""Immutable development-gate evaluation contracts."""

from enum import StrEnum, unique
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


@unique
class PromotionGate(StrEnum):
    """Every preregistered condition required before holdout authorization."""

    MEAN_RANK_IC = "mean_rank_ic"
    MINIMUM_FOLD_RANK_IC = "minimum_fold_rank_ic"
    DIRECTION_CONSISTENCY = "direction_consistency"
    TOTAL_RETURN_OUTPERFORMANCE = "total_return_outperformance"
    SHARPE_OUTPERFORMANCE = "sharpe_outperformance"
    NO_RISK_HALT = "no_risk_halt"
    COMPLETE_INDUSTRY_PIT = "complete_industry_pit"


@unique
class PromotionDecision(StrEnum):
    """Development-only outcome; neither state opens the final holdout."""

    BLOCKED = "BLOCKED"
    ELIGIBLE_FOR_MANUAL_AUTHORIZATION = "ELIGIBLE_FOR_MANUAL_AUTHORIZATION"


class FrozenPromotionModel(BaseModel):
    """Strict immutable boundary for promotion evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PromotionGateResult(FrozenPromotionModel):
    """Observed and required values for one frozen gate."""

    gate: PromotionGate
    passed: bool
    observed: str = Field(min_length=1)
    requirement: str = Field(min_length=1)


class ModelPromotionEvaluation(FrozenPromotionModel):
    """Complete development decision without final-test authority."""

    protocol_id: str = Field(pattern=r"^model_protocol_[0-9a-f]{64}$")
    model_id: str = Field(pattern=r"^ridge_model_[0-9a-f]{64}$")
    diagnostic_report_id: str = Field(pattern=r"^model_diagnostic_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    checks: tuple[PromotionGateResult, ...] = Field(min_length=7, max_length=7)
    decision: PromotionDecision
    final_holdout_authorized: Literal[False]
    model_status: Literal["DRAFT"]
    final_test_runs: Literal[0]

    @model_validator(mode="after")
    def decision_matches_complete_gate_set(self) -> Self:
        """Reject missing, duplicate, reordered, or relabelled gate outcomes."""
        gates = tuple(item.gate for item in self.checks)
        if gates != tuple(PromotionGate):
            detail = "promotion checks must contain every gate in canonical order"
            raise ValueError(detail)
        expected = (
            PromotionDecision.ELIGIBLE_FOR_MANUAL_AUTHORIZATION
            if all(item.passed for item in self.checks)
            else PromotionDecision.BLOCKED
        )
        if self.decision is not expected:
            detail = "promotion decision differs from gate outcomes"
            raise ValueError(detail)
        return self
