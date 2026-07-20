from pathlib import Path

import pytest

from ashare_lab.ml.contracts import ModelArtifact, TrainerJob
from ashare_lab.ml.registry import ModelStatus
from ashare_lab.research.experiments.manifest import ModelFamily
from ashare_lab.research.model_governance import ModelGovernanceError
from ashare_lab.services.training import TrainingService, TrainingServiceError

from .training_support import build_training_evidence, folds, training_frame


class RecordingTrainer:
    """Record calls so tests can prove the artifact guard runs first."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_family(self) -> ModelFamily:
        return ModelFamily.RIDGE

    def train(self, job: TrainerJob) -> ModelArtifact:
        self.calls += 1
        return ModelArtifact(
            model_id="model_001",
            training_run_id=job.experiment.training_run_id,
            dataset_snapshot_id=job.experiment.dataset_snapshot_id,
            artifact_uri="artifacts/model_001.json",
            artifact_sha256="a" * 64,
        )


class WrongFamilyTrainer(RecordingTrainer):
    """Declare a different family to prove dispatch is closed over the manifest."""

    @property
    def model_family(self) -> ModelFamily:
        return ModelFamily.LIGHTGBM_RANKER


def test_training_service_rejects_tampered_dataset_before_trainer(tmp_path: Path) -> None:
    # Given: valid evidence whose DatasetSpec bytes are altered after publication.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    evidence.dataset_descriptor.manifest_path.write_text("{}", encoding="utf-8")
    trainer = RecordingTrainer()

    # When / Then: actual artifact verification fails before trainer code executes.
    with pytest.raises(ModelGovernanceError, match="dataset"):
        TrainingService(trainer).train(evidence, experiment, folds(), frame)
    assert trainer.calls == 0


def test_training_service_rejects_tampered_lineage_before_trainer(tmp_path: Path) -> None:
    # Given: a lineage document whose bytes no longer match its descriptor.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    evidence.lineage_descriptor.path.write_text("{}", encoding="utf-8")
    trainer = RecordingTrainer()

    # When / Then: field lineage cannot be replaced by caller booleans.
    with pytest.raises(ModelGovernanceError, match="lineage"):
        TrainingService(trainer).train(evidence, experiment, folds(), frame)
    assert trainer.calls == 0


def test_training_service_creates_draft_record_after_approval(tmp_path: Path) -> None:
    # Given: verified development artifacts and an internal Ridge adapter.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    trainer = RecordingTrainer()

    # When: the sole training service approves and executes the job.
    result = TrainingService(trainer).train(evidence, experiment, folds(), frame)

    # Then: one trainer call yields a DRAFT model linked to the approved run.
    assert trainer.calls == 1
    assert result.record.status is ModelStatus.DRAFT
    assert result.record.training_run_id == experiment.training_run_id
    assert result.approval.approved is True


def test_training_service_rejects_trainer_family_mismatch(tmp_path: Path) -> None:
    # Given: a Ridge experiment paired with an adapter declaring LightGBM.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    trainer = WrongFamilyTrainer()

    # When / Then: dispatch stops before governance or trainer execution.
    with pytest.raises(TrainingServiceError, match="model family mismatch"):
        TrainingService(trainer).train(evidence, experiment, folds(), frame)
    assert trainer.calls == 0
