"""Sole orchestration entrypoint for governed model training."""

from dataclasses import dataclass

import polars as pl

from ashare_lab.ml.contracts import ModelArtifact, Trainer, TrainerJob
from ashare_lab.ml.registry import (
    DatasetSnapshotId,
    ModelId,
    ModelRecord,
    ModelStatus,
    TrainingRunId,
)
from ashare_lab.research.experiments.manifest import ExperimentManifest
from ashare_lab.research.model_evidence import DevelopmentTrainingEvidence
from ashare_lab.research.model_governance import ModelTrainingGuard, TrainingApproval
from ashare_lab.research.splits.walk_forward import WalkForwardFold


@dataclass(frozen=True, slots=True)
class GovernedTrainingResult:
    """DRAFT model artifact and rulebook evidence from one approved run."""

    artifact: ModelArtifact
    approval: TrainingApproval
    record: ModelRecord


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
    """Verify actual artifacts before invoking one internal trainer."""

    def __init__(self, trainer: Trainer) -> None:
        """Bind one internal trainer behind the non-bypassable service entrypoint."""
        self._trainer = trainer

    def train(
        self,
        evidence: DevelopmentTrainingEvidence,
        experiment: ExperimentManifest,
        folds: tuple[WalkForwardFold, ...],
        frame: pl.DataFrame,
    ) -> GovernedTrainingResult:
        """Approve development evidence, execute once, and register DRAFT only."""
        if self._trainer.model_family is not experiment.model_family:
            raise TrainingServiceError(
                experiment.model_family.value,
                self._trainer.model_family.value,
            )
        decision = ModelTrainingGuard().approve_development(evidence, experiment, folds, frame)
        artifact = self._trainer.train(
            TrainerJob(
                experiment=experiment,
                folds=folds,
                frame=frame,
                preprocessors=decision.inputs.preprocessors,
                artifact_root=evidence.artifact_root,
            )
        )
        record = ModelRecord(
            model_id=ModelId(artifact.model_id),
            dataset_snapshot_id=DatasetSnapshotId(artifact.dataset_snapshot_id),
            training_run_id=TrainingRunId(artifact.training_run_id),
            status=ModelStatus.DRAFT,
        )
        return GovernedTrainingResult(artifact, decision.approval, record)
