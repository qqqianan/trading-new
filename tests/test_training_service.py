from datetime import date

import pytest

from ashare_lab.ml.contracts import ModelArtifact
from ashare_lab.research.experiments.manifest import ExperimentManifest
from ashare_lab.research.model_governance import (
    ModelGovernanceError,
    ModelPurpose,
    TrainingManifest,
    ValidationScheme,
)
from ashare_lab.research.splits.walk_forward import WalkForwardFold
from ashare_lab.services.training import TrainingService


class RecordingTrainer:
    """Record calls so tests can prove the governance gate runs first."""

    def __init__(self) -> None:
        self.calls = 0
        self.fold_count = 0

    def train(
        self,
        manifest: ExperimentManifest,
        folds: tuple[WalkForwardFold, ...],
    ) -> ModelArtifact:
        self.calls += 1
        self.fold_count = len(folds)
        return ModelArtifact(
            model_id="model_001",
            training_run_id=manifest.training_run_id,
            dataset_snapshot_id=manifest.dataset_snapshot_id,
            artifact_uri="artifacts/model_001.bin",
            artifact_sha256="a" * 64,
        )


def _experiment() -> ExperimentManifest:
    return ExperimentManifest(
        training_run_id="run_001",
        dataset_snapshot_id="ds_abc123",
        schema_manifest_id="schema_abc123",
        lineage_manifest_id="lineage_abc123",
        rulebook_version="1.1.0",
        git_commit="abcdef1",
        model_family="ridge",
        feature_names=("momentum_20d",),
        label_name="open_to_open_20d",
        split_protocol="purged_walk_forward_v1",
        random_seed=7,
        final_test_runs=1,
    )


def _protocol(*, complete_data_lineage: bool) -> TrainingManifest:
    return TrainingManifest(
        purpose=ModelPurpose.INVESTMENT_DECISION,
        validation_scheme=ValidationScheme.PURGED_WALK_FORWARD,
        uses_synthetic_data=False,
        point_in_time_features=True,
        survivorship_safe_universe=True,
        preprocessing_fit_on_train_only=True,
        final_test_runs=1,
        reproducible_snapshot=True,
        complete_schema_documentation=True,
        complete_data_lineage=complete_data_lineage,
        selection_trials=1,
        multiple_testing_control=False,
    )


def test_training_service_never_calls_trainer_when_governance_rejects() -> None:
    # Given: a trainer and a protocol with broken data lineage.
    trainer = RecordingTrainer()
    service = TrainingService(trainer)

    # When / Then: the guard rejects before trainer code can execute.
    with pytest.raises(ModelGovernanceError, match="complete_data_lineage"):
        service.train(_protocol(complete_data_lineage=False), _experiment(), ())
    assert trainer.calls == 0


def test_training_service_calls_trainer_after_governance_approval() -> None:
    # Given: a valid protocol, immutable experiment, and one time-ordered fold.
    trainer = RecordingTrainer()
    service = TrainingService(trainer)
    fold = WalkForwardFold(
        fold_index=0,
        train=(date(2020, 1, 1), date(2020, 12, 31)),
        validation=(date(2021, 2, 1), date(2021, 6, 30)),
        test=(date(2021, 8, 1), date(2021, 12, 31)),
    )

    # When: the sole public training service executes the approved request.
    result = service.train(_protocol(complete_data_lineage=True), _experiment(), (fold,))

    # Then: one trainer call produces an artifact bound to the approved run.
    assert trainer.calls == 1
    assert trainer.fold_count == 1
    assert result.artifact.training_run_id == "run_001"
    assert result.approval.approved is True
