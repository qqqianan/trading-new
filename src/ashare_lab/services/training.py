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
        approval = ModelTrainingGuard().approve(protocol)
        artifact = self._trainer.train(experiment, folds)
        return GovernedTrainingResult(artifact=artifact, approval=approval)
