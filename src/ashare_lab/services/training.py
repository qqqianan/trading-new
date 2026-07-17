"""Sole orchestration entrypoint for governed model training."""

from dataclasses import dataclass

from ashare_lab.ml.contracts import ModelArtifact, Trainer
from ashare_lab.research.experiments.manifest import ExperimentManifest
from ashare_lab.research.model_governance import (
    ModelTrainingGuard,
    TrainingApproval,
    TrainingManifest,
)
from ashare_lab.research.splits.walk_forward import WalkForwardFold


@dataclass(frozen=True, slots=True)
class GovernedTrainingResult:
    """Artifact and rulebook evidence produced by one approved run."""

    artifact: ModelArtifact
    approval: TrainingApproval


class TrainingServiceError(Exception):
    """A trainer cannot execute the declared experiment contract."""

    __slots__ = ("declared_family", "trainer_family")

    def __init__(self, declared_family: str, trainer_family: str) -> None:
        """Record the mismatched experiment and implementation families."""
        super().__init__()
        self.declared_family = declared_family
        self.trainer_family = trainer_family

    def __str__(self) -> str:
        """Explain why orchestration refused the concrete trainer."""
        return (
            "model family mismatch: "
            f"experiment={self.declared_family}, trainer={self.trainer_family}"
        )


class TrainingService:
    """Ensure governance approval occurs before any trainer implementation runs."""

    def __init__(self, trainer: Trainer) -> None:
        """Bind one internal trainer behind the non-bypassable service entrypoint."""
        self._trainer = trainer

    def train(
        self,
        protocol: TrainingManifest,
        experiment: ExperimentManifest,
        folds: tuple[WalkForwardFold, ...],
    ) -> GovernedTrainingResult:
        """Approve the protocol first, then execute the bound trainer exactly once."""
        if self._trainer.model_family is not experiment.model_family:
            raise TrainingServiceError(
                experiment.model_family.value,
                self._trainer.model_family.value,
            )
        approval = ModelTrainingGuard().approve(protocol)
        artifact = self._trainer.train(experiment, folds)
        return GovernedTrainingResult(artifact=artifact, approval=approval)
