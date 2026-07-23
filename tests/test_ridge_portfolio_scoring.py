from pathlib import Path

import polars as pl
import pytest

from ashare_lab.ml.trainers.ridge import RidgeTrainer
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.datasets.spec_store import DatasetSpecStore
from ashare_lab.research.preprocessing.models import FoldPreprocessingArtifact
from ashare_lab.research.preprocessing.store import FoldPreprocessorStore
from ashare_lab.services import model_prediction
from ashare_lab.services.model_prediction import (
    RidgePredictionFrameError,
    build_ridge_prediction_score_frame,
)
from ashare_lab.services.ridge_portfolio_runtime import (
    CompleteRidgeScoreRequest,
    assemble_complete_ridge_portfolio_scores,
)
from ashare_lab.services.training import TrainingService

from .training_support import LABEL, build_training_evidence, folds, training_frame


class MemoryArtifactReader:
    """Record exact artifact capabilities used by complete score assembly."""

    def __init__(self, frames: dict[tuple[ArtifactKind, str], pl.DataFrame]) -> None:
        self._frames = frames
        self.calls: list[ArtifactKind] = []

    def read(self, kind: ArtifactKind, artifact_id: str) -> pl.DataFrame:
        self.calls.append(kind)
        return self._frames[(kind, artifact_id)]


def _frame_with_missing_test_label() -> pl.DataFrame:
    first_test_day = folds()[0].test[0]
    return training_frame().with_columns(
        pl.when(
            (pl.col("decision_time").dt.date() == first_test_day)
            & (pl.col("symbol") == "000001.SZ")
        )
        .then(None)
        .otherwise(pl.col(LABEL))
        .alias(LABEL)
    )


def _scoring_inputs(
    tmp_path: Path,
) -> tuple[
    RidgeExperimentArtifact,
    tuple[FoldPreprocessingArtifact, ...],
    pl.DataFrame,
    pl.DataFrame,
]:
    frame = _frame_with_missing_test_label()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    store = RidgeArtifactStore(tmp_path)
    trained = TrainingService(RidgeTrainer(tmp_path)).train(
        evidence,
        experiment,
        folds(),
        frame,
    )
    model = store.read(trained.artifact)
    anchor = build_ridge_prediction_score_frame(store.read_predictions(trained.artifact))
    preprocessor_store = FoldPreprocessorStore(tmp_path)
    preprocessors = tuple(
        preprocessor_store.read(descriptor) for descriptor in evidence.preprocessor_descriptors
    )
    return model, preprocessors, frame.drop(LABEL), anchor


def test_complete_ridge_scores_include_rows_without_future_labels(tmp_path: Path) -> None:
    # Given: one investable test row whose future label cannot be evaluated.
    model, preprocessors, feature_frame, anchor = _scoring_inputs(tmp_path)

    # When: frozen fold models score the complete label-free candidate frame.
    scores = model_prediction.build_complete_ridge_score_frame(
        model,
        folds(),
        preprocessors,
        feature_frame,
        anchor,
    )

    # Then: the unlabeled row is scored and persisted evaluation scores are reproduced.
    assert scores.columns == ["decision_time", "symbol", "model_score"]
    assert scores.height == 16
    assert anchor.height == 15
    assert scores["model_score"].is_finite().all()


def test_complete_ridge_scores_reject_preprocessor_lineage_mismatch(tmp_path: Path) -> None:
    # Given: one preprocessor relabeled to a different DatasetSpec.
    model, preprocessors, frame, anchor = _scoring_inputs(tmp_path)
    mismatched = (
        preprocessors[0].model_copy(update={"dataset_snapshot_id": "ds_different"}),
        *preprocessors[1:],
    )

    # When / Then: model scoring stops before applying foreign fitted parameters.
    with pytest.raises(RidgePredictionFrameError, match="lineage differs"):
        model_prediction.build_complete_ridge_score_frame(model, folds(), mismatched, frame, anchor)


def test_complete_ridge_scores_reject_duplicate_feature_keys(tmp_path: Path) -> None:
    # Given: the complete feature frame repeats one investable observation.
    model, preprocessors, frame, anchor = _scoring_inputs(tmp_path)
    duplicated = pl.concat((frame, frame.head(1)))

    # When / Then: repeated rows cannot alter cross-sectional transforms or veto counts.
    with pytest.raises(RidgePredictionFrameError, match="keys are duplicated"):
        model_prediction.build_complete_ridge_score_frame(
            model, folds(), preprocessors, duplicated, anchor
        )


def test_complete_ridge_scores_reject_unknown_anchor_key(tmp_path: Path) -> None:
    # Given: persisted predictions claim one key outside the complete PIT feature frame.
    model, preprocessors, frame, anchor = _scoring_inputs(tmp_path)
    unknown = anchor.head(1).with_columns(pl.lit("999999.SZ").alias("symbol"))

    # When / Then: reconstruction cannot silently discard the unknown prediction.
    with pytest.raises(RidgePredictionFrameError, match="keys are absent"):
        model_prediction.build_complete_ridge_score_frame(
            model, folds(), preprocessors, frame, unknown
        )


def test_complete_ridge_scores_reject_anchor_value_mismatch(tmp_path: Path) -> None:
    # Given: persisted model scores differ from deterministic fold reconstruction.
    model, preprocessors, frame, anchor = _scoring_inputs(tmp_path)
    altered = anchor.with_columns((pl.col("model_score") + 0.1).alias("model_score"))

    # When / Then: the model cannot be admitted to portfolio scoring.
    with pytest.raises(RidgePredictionFrameError, match="differ from persisted"):
        model_prediction.build_complete_ridge_score_frame(
            model, folds(), preprocessors, frame, altered
        )


def test_complete_ridge_runtime_uses_only_universe_and_feature_artifacts(
    tmp_path: Path,
) -> None:
    # Given: a real model/preprocessor store and in-memory governed market artifacts.
    frame = _frame_with_missing_test_label()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    store = RidgeArtifactStore(tmp_path)
    trained = TrainingService(RidgeTrainer(tmp_path)).train(
        evidence,
        experiment,
        folds(),
        frame,
    )
    model = store.read(trained.artifact)
    anchor = build_ridge_prediction_score_frame(store.read_predictions(trained.artifact))
    spec = DatasetSpecStore(tmp_path).read(evidence.dataset_descriptor)
    available = frame["decision_time"]
    universe = frame.select("decision_time", "symbol").with_columns(
        available.alias("available_at"),
        pl.lit(value=True).alias("eligible_for_new_risk"),
    )
    artifact_frames: dict[tuple[ArtifactKind, str], pl.DataFrame] = {
        (ArtifactKind.UNIVERSE, spec.universe_version): universe
    }
    for feature, artifact_id in zip(spec.features, spec.feature_artifact_ids, strict=True):
        artifact_frames[(ArtifactKind.FEATURE, artifact_id)] = frame.select(
            "decision_time",
            "symbol",
            pl.lit(feature.name).alias("feature_id"),
            pl.lit(feature.version).alias("feature_version"),
            pl.col(feature.name).alias("value"),
            available.alias("available_at"),
            pl.lit("QUALIFIED").alias("quality_status"),
        )
    reader = MemoryArtifactReader(artifact_frames)

    # When: runtime reconstructs scores from immutable artifacts.
    scores = assemble_complete_ridge_portfolio_scores(
        CompleteRidgeScoreRequest(tmp_path, spec, model, folds()),
        reader,
        anchor,
    )

    # Then: complete scores are emitted without exercising label capability.
    assert scores.height == 16
    assert ArtifactKind.LABEL not in reader.calls
    assert reader.calls.count(ArtifactKind.UNIVERSE) == 1
