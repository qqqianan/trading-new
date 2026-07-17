"""Non-bypassable protocol gate for future model training pipelines."""

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final

_RULEBOOK_VERSION: Final = "1.1.0"


@unique
class ModelPurpose(StrEnum):
    """Permitted destinations for a trained model."""

    RESEARCH_ONLY = "research_only"
    INVESTMENT_DECISION = "investment_decision"


@unique
class ValidationScheme(StrEnum):
    """Time-respecting validation schemes."""

    WALK_FORWARD = "walk_forward"
    PURGED_WALK_FORWARD = "purged_walk_forward"


@dataclass(frozen=True, slots=True)
class TrainingManifest:
    """Evidence a model pipeline must provide before training is accepted."""

    purpose: ModelPurpose
    validation_scheme: ValidationScheme
    uses_synthetic_data: bool
    point_in_time_features: bool
    survivorship_safe_universe: bool
    preprocessing_fit_on_train_only: bool
    final_test_runs: int
    reproducible_snapshot: bool
    complete_schema_documentation: bool
    complete_data_lineage: bool
    selection_trials: int
    multiple_testing_control: bool


class ModelGovernanceError(Exception):
    """A training protocol violates the quantitative research rulebook."""

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
    """Versioned evidence that every model-training hard gate passed."""

    approved: bool
    rulebook_version: str
    checks: tuple[str, ...]


class ModelTrainingGuard:
    """Reject leakage, test reuse, selection bias, and irreproducibility."""

    def approve(self, manifest: TrainingManifest) -> TrainingApproval:
        """Approve only a fully isolated and reproducible training protocol."""
        match manifest.purpose:
            case ModelPurpose.RESEARCH_ONLY:
                pass
            case ModelPurpose.INVESTMENT_DECISION:
                if manifest.uses_synthetic_data:
                    rule = "real_data_required"
                    detail = "synthetic data cannot train an investment decision model"
                    raise ModelGovernanceError(rule, detail)

        required_checks = (
            (
                manifest.point_in_time_features,
                "point_in_time_features",
                "features include information unavailable at decision time",
            ),
            (
                manifest.survivorship_safe_universe,
                "survivorship_safe_universe",
                "historical universe excludes dead, delisted, or suspended securities",
            ),
            (
                manifest.preprocessing_fit_on_train_only,
                "train_only_preprocessing",
                "preprocessing was fitted outside the training fold",
            ),
            (
                manifest.final_test_runs == 1,
                "final_test_single_use",
                "final test set must be evaluated exactly once after the protocol is frozen",
            ),
            (
                manifest.reproducible_snapshot,
                "reproducible_snapshot",
                "data snapshot and feature lineage are not reproducible",
            ),
            (
                manifest.complete_schema_documentation,
                "complete_schema_documentation",
                "training inputs do not have complete versioned schema documentation",
            ),
            (
                manifest.complete_data_lineage,
                "complete_data_lineage",
                "raw sources cannot be traced through features and labels to the dataset",
            ),
            (
                manifest.selection_trials <= 1 or manifest.multiple_testing_control,
                "multiple_testing_control",
                "multiple model selection trials require false-discovery control",
            ),
        )
        for passed, rule, detail in required_checks:
            if not passed:
                raise ModelGovernanceError(rule, detail)
        return TrainingApproval(
            approved=True,
            rulebook_version=_RULEBOOK_VERSION,
            checks=tuple(rule for _, rule, _ in required_checks),
        )
