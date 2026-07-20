"""Label-free portfolio-facing view of keyed Ridge development predictions."""

import polars as pl

from ashare_lab.ml.trainers.ridge_models import RidgePredictionArtifact
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256

_KEYS = ("decision_time", "symbol")


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
