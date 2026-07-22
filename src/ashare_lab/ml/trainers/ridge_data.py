"""Fold-local transformation and typed matrices for Ridge training."""

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import polars as pl
from numpy.typing import NDArray
from pydantic import TypeAdapter

from ashare_lab.ml.contracts import TrainerJob
from ashare_lab.research.preprocessing import FoldPreprocessor
from ashare_lab.research.preprocessing.models import FoldPreprocessingArtifact
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256
from ashare_lab.research.splits.walk_forward import WalkForwardFold
from ashare_lab.research.training.targets import TRAINING_TARGET_COLUMN, attach_training_target

_DATETIMES = TypeAdapter(tuple[datetime, ...])
_SYMBOLS = TypeAdapter(tuple[str, ...])


class RidgeTrainingError(Exception):
    """Verified inputs cannot form finite Ridge matrices."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed Ridge fitting failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the Ridge boundary and concrete failure."""
        return f"ridge_training: {self.detail}"


@dataclass(frozen=True, slots=True)
class PreparedFold:
    """Train, validation, and internal-test matrices for one approved fold."""

    fold_index: int
    train_x: NDArray[np.float64]
    train_y: NDArray[np.float64]
    validation_x: NDArray[np.float64]
    validation_y: NDArray[np.float64]
    test_x: NDArray[np.float64]
    test_y: NDArray[np.float64]
    test_raw_y: NDArray[np.float64]
    test_keys_sha256: str
    test_decision_times: tuple[datetime, ...]
    test_symbols: tuple[str, ...]


def model_feature_names(feature_names: tuple[str, ...]) -> tuple[str, ...]:
    """Append fold-generated missing indicators in stable model order."""
    return (*feature_names, *(f"{name}_missing" for name in feature_names))


def prepare_fold(
    job: TrainerJob,
    fold: WalkForwardFold,
    artifact: FoldPreprocessingArtifact,
) -> PreparedFold:
    """Transform each partition using only the already-fitted training artifact."""
    preprocessor = FoldPreprocessor(
        job.experiment.feature_names,
        job.experiment.size_feature_name,
    )
    train = _partition(job.frame, fold.train, job.experiment.label_name)
    validation = _partition(job.frame, fold.validation, job.experiment.label_name)
    test = _partition(job.frame, fold.test, job.experiment.label_name)
    columns = model_feature_names(job.experiment.feature_names)
    transformed_train = attach_training_target(
        preprocessor.transform(train, artifact),
        job.experiment.label_name,
        job.experiment.label_transform,
    )
    transformed_validation = attach_training_target(
        preprocessor.transform(validation, artifact),
        job.experiment.label_name,
        job.experiment.label_transform,
    )
    transformed_test = attach_training_target(
        preprocessor.transform(test, artifact),
        job.experiment.label_name,
        job.experiment.label_transform,
    )
    return PreparedFold(
        fold_index=fold.fold_index,
        train_x=_matrix(transformed_train, columns),
        train_y=_labels(transformed_train, TRAINING_TARGET_COLUMN),
        validation_x=_matrix(transformed_validation, columns),
        validation_y=_labels(transformed_validation, TRAINING_TARGET_COLUMN),
        test_x=_matrix(transformed_test, columns),
        test_y=_labels(transformed_test, TRAINING_TARGET_COLUMN),
        test_raw_y=_labels(transformed_test, job.experiment.label_name),
        test_keys_sha256=training_frame_sha256(test.select("decision_time", "symbol")),
        test_decision_times=_DATETIMES.validate_python(test["decision_time"].to_list()),
        test_symbols=_SYMBOLS.validate_python(test["symbol"].to_list()),
    )


def _partition(frame: pl.DataFrame, dates: tuple[date, ...], label_name: str) -> pl.DataFrame:
    result = frame.filter(
        pl.col("decision_time").dt.date().is_in(dates)
        & pl.col(label_name).is_not_null()
        & pl.col(label_name).is_finite()
    )
    if result.is_empty():
        detail = "fold partition has no finite labeled rows"
        raise RidgeTrainingError(detail)
    return result


def _matrix(frame: pl.DataFrame, columns: tuple[str, ...]) -> NDArray[np.float64]:
    values = frame.select(pl.col(name).cast(pl.Float64).alias(name) for name in columns).to_numpy()
    matrix = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(matrix)):
        detail = "model matrix contains non-finite values"
        raise RidgeTrainingError(detail)
    return matrix


def _labels(frame: pl.DataFrame, label_name: str) -> NDArray[np.float64]:
    labels = np.asarray(frame[label_name].to_numpy(), dtype=np.float64)
    if not np.all(np.isfinite(labels)):
        detail = "label vector contains non-finite values"
        raise RidgeTrainingError(detail)
    return labels
