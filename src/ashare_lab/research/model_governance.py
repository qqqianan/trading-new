"""Artifact-backed model training and promotion governance."""

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, Never

import polars as pl

from ashare_lab.research.experiments.manifest import ExperimentManifest
from ashare_lab.research.model_evidence import (
    DevelopmentTrainingEvidence,
    ModelPurpose,
    TrainingDataKind,
    TrainingEvidenceError,
    VerifiedDevelopmentInputs,
    verify_development_evidence,
)
from ashare_lab.research.splits.final_holdout import FinalHoldoutAccessLedger, FinalHoldoutError
from ashare_lab.research.splits.walk_forward import WalkForwardFold

_RULEBOOK_VERSION: Final = "1.1.0"


@unique
class ApprovalScope(StrEnum):
    """Authority granted by one governance decision."""

    DEVELOPMENT_TRAINING = "development_training"
    VALIDATION_PROMOTION = "validation_promotion"


class ModelGovernanceError(Exception):
    """Actual training evidence violates the quantitative rulebook."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: str, detail: str) -> None:
        """Create a typed governance rejection."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the rejected rule and concrete reason."""
        return f"{self.rule}: {self.detail}"


@dataclass(frozen=True, slots=True)
class TrainingApproval:
    """Versioned evidence granting only one explicit authority scope."""

    approved: bool
    scope: ApprovalScope
    rulebook_version: str
    checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DevelopmentTrainingDecision:
    """Approval plus verified artifacts passed to the sole service entrypoint."""

    approval: TrainingApproval
    inputs: VerifiedDevelopmentInputs


class ModelTrainingGuard:
    """Verify immutable artifacts and keep the final holdout sealed during fitting."""

    def approve_development(
        self,
        evidence: DevelopmentTrainingEvidence,
        experiment: ExperimentManifest,
        folds: tuple[WalkForwardFold, ...],
        frame: pl.DataFrame,
    ) -> DevelopmentTrainingDecision:
        """Approve DRAFT training only from verified development artifacts."""
        if experiment.final_test_runs != 0:
            _reject("final_holdout_sealed", "final test must remain sealed during development")
        if (
            evidence.purpose is ModelPurpose.INVESTMENT_DECISION
            and evidence.data_kind is TrainingDataKind.SYNTHETIC_QA
        ):
            _reject("real_data_required", "synthetic data cannot train an investment model")
        try:
            holdout_count = FinalHoldoutAccessLedger(evidence.holdout_ledger_root).count(
                evidence.holdout_spec_id
            )
        except FinalHoldoutError as error:
            _reject("final_holdout_ledger", str(error))
        if holdout_count != 0:
            _reject("final_holdout_sealed", "final holdout was already opened")
        try:
            inputs = verify_development_evidence(evidence, experiment, folds, frame)
        except TrainingEvidenceError as error:
            _reject(error.rule, error.detail)
        checks = (
            "dataset_spec_verified",
            "training_schema_verified",
            "field_lineage_verified",
            "fold_preprocessors_verified",
            "development_frame_verified",
            "final_holdout_sealed",
        )
        return DevelopmentTrainingDecision(
            approval=TrainingApproval(
                approved=True,
                scope=ApprovalScope.DEVELOPMENT_TRAINING,
                rulebook_version=_RULEBOOK_VERSION,
                checks=checks,
            ),
            inputs=inputs,
        )


def _reject(rule: str, detail: str) -> Never:
    raise ModelGovernanceError(rule, detail)
