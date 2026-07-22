from pathlib import Path

import pytest
from pydantic import ValidationError

from ashare_lab.ml.contracts import ModelArtifact, TrainerJob
from ashare_lab.ml.trainers import ridge as ridge_module
from ashare_lab.ml.trainers.ridge import RidgeTrainer
from ashare_lab.ml.trainers.ridge_data import RidgeTrainingError, prepare_fold
from ashare_lab.ml.trainers.ridge_models import FoldPredictionBatch
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.research.experiments.manifest import ExperimentManifest
from ashare_lab.research.preprocessing.store import FoldPreprocessorStore
from ashare_lab.services.training import TrainingService

from .training_support import build_training_evidence, folds, training_frame


def test_ridge_saves_equal_weight_baseline_and_all_alpha_candidates(tmp_path: Path) -> None:
    # Given: two verified development folds and the frozen four-alpha grid.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    trainer = RidgeTrainer(tmp_path)

    # When: governed Ridge training completes.
    result = TrainingService(trainer).train(evidence, experiment, folds(), frame)
    store = RidgeArtifactStore(tmp_path)
    artifact = store.read(result.artifact)
    predictions = store.read_predictions(result.artifact)

    # Then: baseline, every candidate, selected alpha, and prediction lineage are saved.
    assert {item.alpha for item in artifact.candidate_results} == {0.1, 1.0, 10.0, 100.0}
    assert len(artifact.fold_results) == 2
    assert all(
        len(item.coefficients) == len(artifact.model_feature_names) and item.intercept is not None
        for item in artifact.fold_results
    )
    assert artifact.baseline_mean_validation_mse >= 0
    assert artifact.selected_alpha in {0.1, 1.0, 10.0, 100.0}
    assert artifact.prediction_lineage_id.startswith("prediction_lineage_")
    assert all(batch.decision_times and batch.symbols for batch in predictions.batches)
    assert all(
        len(batch.decision_times) == len(batch.symbols) == len(batch.predictions)
        for batch in predictions.batches
    )
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


def test_ridge_prediction_batch_rejects_misaligned_value_vectors() -> None:
    # Given: predictions and labels with different row counts.
    # When / Then: an ambiguous evaluation artifact cannot be constructed.
    with pytest.raises(ValidationError, match="prediction and label rows differ"):
        FoldPredictionBatch(
            fold_index=0,
            observation_keys_sha256="a" * 64,
            predictions=(0.1, 0.2),
            labels=(0.3,),
        )


def test_rank_ridge_uses_per_date_rank_target_and_preserves_raw_test_labels(
    tmp_path: Path,
) -> None:
    # Given: a protocol-bound rank Ridge experiment over ordered daily cross-sections.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    payload = experiment.model_dump(mode="json")
    payload.update(
        {
            "model_family": "ridge_rank",
            "label_transform": "cross_sectional_percentile_rank",
            "experiment_protocol_id": "model_protocol_" + "f" * 64,
        }
    )
    rank_experiment = ExperimentManifest.model_validate(payload)
    artifact = FoldPreprocessorStore(tmp_path).read(evidence.preprocessor_descriptors[0])
    job = TrainerJob(rank_experiment, folds(), frame, (artifact,), tmp_path)

    # When: the first fold is converted to typed model matrices.
    prepared = prepare_fold(job, folds()[0], artifact)

    # Then: fitting uses [0, 1] cross-sectional ranks while diagnostics retain returns.
    assert prepared.train_y[:4].tolist() == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])
    assert prepared.test_raw_y[:4].tolist() == pytest.approx([-0.85, -0.55, 0.55, 0.85])


def test_rank_ridge_publishes_protocol_bound_draft_with_raw_diagnostic_labels(
    tmp_path: Path,
) -> None:
    # Given: governed evidence and a rank-label experiment bound to one protocol.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    payload = experiment.model_dump(mode="json")
    payload.update(
        {
            "model_family": "ridge_rank",
            "label_transform": "cross_sectional_percentile_rank",
            "experiment_protocol_id": "model_protocol_" + "f" * 64,
        }
    )
    rank_experiment = ExperimentManifest.model_validate(payload)
    trainer = ridge_module.RidgeRankTrainer(tmp_path)

    # When: the only TrainingService authorizes and fits the candidate.
    result = TrainingService(trainer).train(evidence, rank_experiment, folds(), frame)

    # Then: the artifact declares its frozen objective and keeps raw-return labels for IC.
    artifact = RidgeArtifactStore(tmp_path).read(result.artifact)
    predictions = RidgeArtifactStore(tmp_path).read_predictions(result.artifact)
    assert artifact.model_family.value == "ridge_rank"
    assert artifact.experiment_protocol_id == "model_protocol_" + "f" * 64
    assert artifact.label_transform.value == "cross_sectional_percentile_rank"
    assert artifact.prediction_label_semantics == "raw_forward_return_for_diagnostics"
    assert predictions.batches[0].labels[:4] == pytest.approx((-0.85, -0.55, 0.55, 0.85))
