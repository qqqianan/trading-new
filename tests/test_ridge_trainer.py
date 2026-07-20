from pathlib import Path

import pytest

from ashare_lab.ml.contracts import ModelArtifact, TrainerJob
from ashare_lab.ml.trainers.ridge import RidgeTrainer
from ashare_lab.ml.trainers.ridge_data import RidgeTrainingError
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.services.training import TrainingService

from .training_support import build_training_evidence, folds, training_frame


def test_ridge_saves_equal_weight_baseline_and_all_alpha_candidates(tmp_path: Path) -> None:
    # Given: two verified development folds and the frozen four-alpha grid.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    trainer = RidgeTrainer(tmp_path)

    # When: governed Ridge training completes.
    result = TrainingService(trainer).train(evidence, experiment, folds(), frame)
    artifact = RidgeArtifactStore(tmp_path).read(result.artifact)

    # Then: baseline, every candidate, selected alpha, and prediction lineage are saved.
    assert {item.alpha for item in artifact.candidate_results} == {0.1, 1.0, 10.0, 100.0}
    assert len(artifact.fold_results) == 2
    assert artifact.baseline_mean_validation_mse >= 0
    assert artifact.selected_alpha in {0.1, 1.0, 10.0, 100.0}
    assert artifact.prediction_lineage_id.startswith("prediction_lineage_")
    assert artifact.final_test_runs == 0


def test_internal_test_labels_cannot_change_alpha_selection(tmp_path: Path) -> None:
    # Given: two datasets differing only in the latest fold's internal test labels.
    original = training_frame()
    shifted = training_frame(test_label_shift=100.0)
    original_root = tmp_path / "original"
    shifted_root = tmp_path / "shifted"
    original_evidence, original_experiment = build_training_evidence(original_root, original)
    shifted_evidence, shifted_experiment = build_training_evidence(shifted_root, shifted)

    # When: each dataset is trained through its own governed service.
    original_result = TrainingService(RidgeTrainer(original_root)).train(
        original_evidence, original_experiment, folds(), original
    )
    shifted_result = TrainingService(RidgeTrainer(shifted_root)).train(
        shifted_evidence, shifted_experiment, folds(), shifted
    )

    # Then: validation-only selection is unchanged while internal test loss changes.
    original_artifact = RidgeArtifactStore(original_root).read(original_result.artifact)
    shifted_artifact = RidgeArtifactStore(shifted_root).read(shifted_result.artifact)
    assert shifted_artifact.selected_alpha == original_artifact.selected_alpha
    assert shifted_artifact.internal_test_mean_mse != pytest.approx(
        original_artifact.internal_test_mean_mse
    )


def test_ridge_store_rejects_tampered_model_manifest(tmp_path: Path) -> None:
    # Given: one governed Ridge artifact modified after publication.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    result = TrainingService(RidgeTrainer(tmp_path)).train(evidence, experiment, folds(), frame)
    Path(result.artifact.artifact_uri).write_text("{}", encoding="utf-8")

    # When / Then: the model hash fails closed before coefficients can be read.
    with pytest.raises(RidgeArtifactStoreError, match="invalid"):
        RidgeArtifactStore(tmp_path).read(result.artifact)


def test_ridge_store_returns_same_descriptor_for_repeated_write(tmp_path: Path) -> None:
    # Given: one governed Ridge artifact already published by content identity.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    trainer = RidgeTrainer(tmp_path)
    original = TrainingService(trainer).train(evidence, experiment, folds(), frame)

    # When: the exact same governed job is trained and written again.
    repeated = TrainingService(trainer).train(evidence, experiment, folds(), frame)

    # Then: publication is deterministic and does not create a second model identity.
    assert repeated.artifact == original.artifact


def test_ridge_store_rejects_descriptor_outside_model_directory(tmp_path: Path) -> None:
    # Given: a valid model descriptor whose URI is relabeled to another path.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    result = TrainingService(RidgeTrainer(tmp_path)).train(evidence, experiment, folds(), frame)
    descriptor = ModelArtifact(
        model_id=result.artifact.model_id,
        training_run_id=result.artifact.training_run_id,
        dataset_snapshot_id=result.artifact.dataset_snapshot_id,
        artifact_uri=str(tmp_path / "elsewhere.json"),
        artifact_sha256=result.artifact.artifact_sha256,
    )

    # When / Then: the store refuses path traversal across its artifact boundary.
    with pytest.raises(RidgeArtifactStoreError, match="crosses"):
        RidgeArtifactStore(tmp_path).read(descriptor)


def test_ridge_store_rejects_tampered_predictions(tmp_path: Path) -> None:
    # Given: valid predictions altered independently from their model manifest.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    result = TrainingService(RidgeTrainer(tmp_path)).train(evidence, experiment, folds(), frame)
    Path(result.artifact.artifact_uri).with_name("predictions.json").write_text(
        "{}", encoding="utf-8"
    )

    # When / Then: prediction lineage bytes fail closed during model loading.
    with pytest.raises(RidgeArtifactStoreError, match="invalid"):
        RidgeArtifactStore(tmp_path).read(result.artifact)


def test_ridge_requires_one_preprocessor_per_fold(tmp_path: Path) -> None:
    # Given: a direct trainer job with folds but no verified preprocessors.
    frame = training_frame()
    _, experiment = build_training_evidence(tmp_path, frame)
    job = TrainerJob(experiment, folds(), frame, (), tmp_path)

    # When / Then: the concrete adapter cannot be called with incomplete evidence.
    with pytest.raises(RidgeTrainingError, match="one verified preprocessor"):
        RidgeTrainer(tmp_path).train(job)
