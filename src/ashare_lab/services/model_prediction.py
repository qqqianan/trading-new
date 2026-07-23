"""Label-free portfolio-facing view of keyed Ridge development predictions."""

from typing import Final

import numpy as np
import polars as pl

from ashare_lab.ml.trainers.ridge_data import model_feature_names
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact, RidgePredictionArtifact
from ashare_lab.research.preprocessing import FoldPreprocessor
from ashare_lab.research.preprocessing.models import FoldPreprocessingArtifact
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256
from ashare_lab.research.splits.walk_forward import WalkForwardFold

_KEYS = ("decision_time", "symbol")
_SCORE_TOLERANCE: Final = 1e-12


class RidgePredictionFrameError(Exception):
    """Prediction rows cannot prove their exact observation identity."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed prediction-key failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the model-score boundary and blocker."""
        return f"ridge_prediction_frame: {self.detail}"


def build_ridge_prediction_score_frame(predictions: RidgePredictionArtifact) -> pl.DataFrame:
    """Verify every keyed batch and expose scores without labels."""
    return build_ridge_prediction_evaluation_frame(predictions).select(
        "decision_time",
        "symbol",
        "model_score",
    )


def build_ridge_prediction_evaluation_frame(
    predictions: RidgePredictionArtifact,
) -> pl.DataFrame:
    """Verify keyed batches while retaining labels only for development diagnostics."""
    frames: list[pl.DataFrame] = []
    for batch in predictions.batches:
        if not batch.decision_times or not batch.symbols:
            detail = f"observation keys are absent for fold {batch.fold_index}"
            raise RidgePredictionFrameError(detail)
        frame = pl.DataFrame(
            {
                "decision_time": pl.Series(
                    "decision_time",
                    batch.decision_times,
                    dtype=pl.Datetime("us", "Asia/Shanghai"),
                ),
                "symbol": batch.symbols,
                "fold_index": [batch.fold_index] * len(batch.predictions),
                "model_score": batch.predictions,
                "label_value": batch.labels,
            }
        )
        if training_frame_sha256(frame.select(*_KEYS)) != batch.observation_keys_sha256:
            detail = f"observation key hash differs for fold {batch.fold_index}"
            raise RidgePredictionFrameError(detail)
        frames.append(frame)
    result = pl.concat(frames).sort(*_KEYS)
    if result.select(*_KEYS).is_duplicated().any():
        detail = "internal-test prediction keys overlap across folds"
        raise RidgePredictionFrameError(detail)
    return result


def build_complete_ridge_score_frame(
    model: RidgeExperimentArtifact,
    folds: tuple[WalkForwardFold, ...],
    preprocessors: tuple[FoldPreprocessingArtifact, ...],
    feature_frame: pl.DataFrame,
    anchor_scores: pl.DataFrame,
) -> pl.DataFrame:
    """Score every eligible test row and verify persisted evaluation predictions."""
    _validate_complete_score_inputs(model, folds, preprocessors, feature_frame, anchor_scores)
    frames = tuple(
        _score_fold(model, fold, preprocessor, feature_frame)
        for fold, preprocessor in zip(folds, preprocessors, strict=True)
    )
    result = pl.concat(frames).sort(*_KEYS)
    if result.select(*_KEYS).is_duplicated().any():
        detail = "complete Ridge score keys overlap across folds"
        raise RidgePredictionFrameError(detail)
    if not result.select(pl.col("model_score").is_finite().all()).item():
        detail = "complete Ridge scores must be finite"
        raise RidgePredictionFrameError(detail)
    _verify_anchor_scores(result, anchor_scores)
    return result


def _validate_complete_score_inputs(
    model: RidgeExperimentArtifact,
    folds: tuple[WalkForwardFold, ...],
    preprocessors: tuple[FoldPreprocessingArtifact, ...],
    feature_frame: pl.DataFrame,
    anchor_scores: pl.DataFrame,
) -> None:
    fold_indices = tuple(item.fold_index for item in folds)
    result_indices = tuple(item.fold_index for item in model.fold_results)
    size_feature = preprocessors[0].size_feature_name if preprocessors else ""
    score_features = (
        model.training_feature_names
        if size_feature in model.training_feature_names
        else (*model.training_feature_names, size_feature)
    )
    expected_columns = [*_KEYS, *score_features]
    if (
        not folds
        or len(folds) != len(preprocessors)
        or fold_indices != result_indices
        or model.model_feature_names != model_feature_names(model.training_feature_names)
        or feature_frame.columns != expected_columns
        or anchor_scores.columns != [*_KEYS, "model_score"]
        or anchor_scores.is_empty()
    ):
        detail = "model, folds, preprocessors, features, or anchor contract differs"
        raise RidgePredictionFrameError(detail)
    if any(
        artifact.dataset_snapshot_id != model.dataset_snapshot_id
        or artifact.feature_names != model.training_feature_names
        for artifact in preprocessors
    ):
        detail = "preprocessor lineage differs from the Ridge model"
        raise RidgePredictionFrameError(detail)
    if (
        feature_frame.select(*_KEYS).is_duplicated().any()
        or anchor_scores.select(*_KEYS).is_duplicated().any()
    ):
        detail = "complete feature or anchor score keys are duplicated"
        raise RidgePredictionFrameError(detail)


def _score_fold(
    model: RidgeExperimentArtifact,
    fold: WalkForwardFold,
    artifact: FoldPreprocessingArtifact,
    feature_frame: pl.DataFrame,
) -> pl.DataFrame:
    frame = feature_frame.filter(pl.col("decision_time").dt.date().is_in(fold.test))
    fold_result = model.fold_results[fold.fold_index]
    if frame.is_empty() or fold_result.intercept is None or not fold_result.coefficients:
        detail = f"fold {fold.fold_index} lacks score rows or fitted coefficients"
        raise RidgePredictionFrameError(detail)
    transformed = FoldPreprocessor(
        model.training_feature_names,
        artifact.size_feature_name,
    ).transform(frame, artifact)
    matrix = np.asarray(
        transformed.select(
            pl.col(name).cast(pl.Float64).alias(name) for name in model.model_feature_names
        ).to_numpy(),
        dtype=np.float64,
    )
    coefficients = np.asarray(fold_result.coefficients, dtype=np.float64)
    scores = matrix @ coefficients + fold_result.intercept
    if not np.all(np.isfinite(scores)):
        detail = f"fold {fold.fold_index} produced non-finite scores"
        raise RidgePredictionFrameError(detail)
    return transformed.select(*_KEYS).with_columns(pl.Series("model_score", scores))


def _verify_anchor_scores(complete: pl.DataFrame, anchor: pl.DataFrame) -> None:
    if anchor.join(complete, on=list(_KEYS), how="anti").height:
        detail = "persisted prediction keys are absent from complete Ridge scores"
        raise RidgePredictionFrameError(detail)
    compared = anchor.join(complete, on=list(_KEYS), how="inner", suffix="_complete")
    differs = compared.filter(
        (pl.col("model_score") - pl.col("model_score_complete")).abs() > _SCORE_TOLERANCE
    )
    if differs.height:
        detail = "complete Ridge scores differ from persisted keyed predictions"
        raise RidgePredictionFrameError(detail)
