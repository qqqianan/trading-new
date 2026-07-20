"""Stable FDR, direction, coverage, and correlation selection decisions."""

from enum import StrEnum, unique
from typing import Final, Self

from pydantic import Field, field_validator, model_validator

from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.factors.correlation import FactorCorrelation
from ashare_lab.research.factors.models import (
    FactorDiagnosticReport,
    FrozenFactorModel,
    stable_metric,
)
from ashare_lab.research.factors.multiple_testing import FdrResult


@unique
class FactorDecisionStatus(StrEnum):
    """Closed factor outcomes after every governance gate."""

    CANDIDATE = "CANDIDATE"
    REJECTED = "REJECTED"


@unique
class FactorDecisionReason(StrEnum):
    """Stable reasons retained for both winners and failed trials."""

    PASSES_DIAGNOSTIC_GATES = "PASSES_DIAGNOSTIC_GATES"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    FDR_NOT_SIGNIFICANT = "FDR_NOT_SIGNIFICANT"
    DIRECTION_INCONSISTENT = "DIRECTION_INCONSISTENT"
    REDUNDANT_HIGH_CORRELATION = "REDUNDANT_HIGH_CORRELATION"


class FactorDecision(FrozenFactorModel):
    """One non-hidden selection outcome linked to its complete diagnostics."""

    trial_id: str
    feature_name: str
    status: FactorDecisionStatus
    reasons: tuple[FactorDecisionReason, ...] = Field(min_length=1)
    p_value: float = Field(ge=0, le=1, allow_inf_nan=False)
    q_value: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("p_value", "q_value")
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze decision evidence to the report precision contract."""
        return stable_metric(value)


class FactorResearchReport(FrozenFactorModel):
    """Complete batch report retaining every trial, diagnostic, and decision."""

    batch_id: str = Field(pattern=r"^trial_batch_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    maximum_q: float = Field(gt=0, le=1)
    diagnostics: tuple[FactorDiagnosticReport, ...] = Field(min_length=1)
    decisions: tuple[FactorDecision, ...] = Field(min_length=1)

    @field_validator("maximum_q")
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze the disclosed FDR threshold precision."""
        return stable_metric(value)

    @model_validator(mode="after")
    def every_diagnostic_has_one_decision(self) -> Self:
        """Reject selective reports that omit failed or inconvenient factors."""
        diagnostics = tuple(item.trial_id for item in self.diagnostics)
        decisions = tuple(item.trial_id for item in self.decisions)
        if diagnostics != decisions or len(set(decisions)) != len(decisions):
            detail = "diagnostics and decisions must retain every trial in exact order"
            raise ValueError(detail)
        return self


class FactorSelectionConfig(FrozenFactorModel):
    """Frozen non-return gates and same-family redundancy threshold."""

    minimum_coverage: float = Field(default=0.60, ge=0, le=1)
    minimum_direction_consistency: float = Field(default=0.50, ge=0, le=1)
    redundancy_threshold: float = Field(default=0.80, ge=0, le=1)


_DEFAULT_SELECTION_CONFIG: Final = FactorSelectionConfig()


def select_factor_candidates(
    trials: tuple[FactorTrial, ...],
    diagnostics: tuple[FactorDiagnosticReport, ...],
    fdr_results: tuple[FdrResult, ...],
    correlations: tuple[FactorCorrelation, ...],
    config: FactorSelectionConfig = _DEFAULT_SELECTION_CONFIG,
) -> tuple[FactorDecision, ...]:
    """Apply fixed gates and deterministic same-family de-duplication."""
    trial_ids = tuple(item.trial_id for item in trials)
    diagnostic_ids = tuple(item.trial_id for item in diagnostics)
    fdr_ids = tuple(item.trial_id for item in fdr_results)
    if trial_ids != diagnostic_ids or trial_ids != fdr_ids:
        detail = "trial, diagnostic, and FDR identities must be complete"
        raise FactorSelectionError(detail)
    reports = {item.trial_id: item for item in diagnostics}
    fdr = {item.trial_id: item for item in fdr_results}
    rejections: dict[str, list[FactorDecisionReason]] = {item.trial_id: [] for item in trials}
    for trial in trials:
        report = reports[trial.trial_id]
        corrected = fdr[trial.trial_id]
        if report.coverage < config.minimum_coverage:
            rejections[trial.trial_id].append(FactorDecisionReason.INSUFFICIENT_COVERAGE)
        if not corrected.significant:
            rejections[trial.trial_id].append(FactorDecisionReason.FDR_NOT_SIGNIFICANT)
        if (
            report.oriented_mean_rank_ic <= 0
            or report.direction_consistency < config.minimum_direction_consistency
        ):
            rejections[trial.trial_id].append(FactorDecisionReason.DIRECTION_INCONSISTENT)
    _reject_redundant(trials, correlations, rejections, config.redundancy_threshold)
    return tuple(
        _decision(trial, reports[trial.trial_id], fdr[trial.trial_id], rejections[trial.trial_id])
        for trial in trials
    )


class FactorSelectionError(Exception):
    """A selection batch omits or aliases registered trial evidence."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed selection failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the selection boundary and concrete failure."""
        return f"factor_selection: {self.detail}"


def _reject_redundant(
    trials: tuple[FactorTrial, ...],
    correlations: tuple[FactorCorrelation, ...],
    rejections: dict[str, list[FactorDecisionReason]],
    threshold: float,
) -> None:
    by_id = {item.trial_id: item for item in trials}
    for item in correlations:
        if abs(item.correlation) < threshold:
            continue
        left = by_id[item.left_trial_id]
        right = by_id[item.right_trial_id]
        if (
            left.family is not right.family
            or rejections[left.trial_id]
            or rejections[right.trial_id]
        ):
            continue
        loser = max((left, right), key=lambda trial: (trial.simplicity_rank, trial.feature_name))
        rejections[loser.trial_id].append(FactorDecisionReason.REDUNDANT_HIGH_CORRELATION)


def _decision(
    trial: FactorTrial,
    report: FactorDiagnosticReport,
    fdr: FdrResult,
    rejections: list[FactorDecisionReason],
) -> FactorDecision:
    reasons = tuple(rejections) or (FactorDecisionReason.PASSES_DIAGNOSTIC_GATES,)
    status = FactorDecisionStatus.REJECTED if rejections else FactorDecisionStatus.CANDIDATE
    return FactorDecision(
        trial_id=trial.trial_id,
        feature_name=trial.feature_name,
        status=status,
        reasons=reasons,
        p_value=report.p_value,
        q_value=fdr.q_value,
    )
