"""Validation-selected scikit-learn Ridge adapter with an equal-factor baseline."""

import hashlib
import json
from pathlib import Path
from typing import Protocol, Self

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import Ridge

from ashare_lab.ml.contracts import ModelArtifact, TrainerJob
from ashare_lab.ml.trainers.ridge_data import (
    PreparedFold,
    RidgeTrainingError,
    model_feature_names,
    prepare_fold,
)
from ashare_lab.ml.trainers.ridge_models import (
    FoldPredictionBatch,
    RidgeArtifactPayload,
    RidgeCandidateResult,
    RidgeFoldResult,
    RidgePredictionArtifact,
)
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.research.experiments.manifest import ModelFamily


class _TypedRidge(Protocol):
    """Narrow typed surface around scikit-learn's broad array API."""

    @property
    def coef_(self) -> NDArray[np.float64]:
        """Return fitted coefficients."""
        ...

    @property
    def intercept_(self) -> float | NDArray[np.float64]:
        """Return the fitted scalar intercept."""
        ...

    def fit(
        self,
        features: NDArray[np.float64],
        labels: NDArray[np.float64],
        /,
    ) -> Self:
        """Fit the regularized linear model."""
        ...

    def predict(self, features: NDArray[np.float64], /) -> NDArray[np.float64]:
        """Return one prediction per feature row."""
        ...


class RidgeTrainer:
    """Fit only the frozen Ridge grid against development validation folds."""

    def __init__(self, artifact_root: Path) -> None:
        """Bind one immutable model artifact root."""
        self._store = RidgeArtifactStore(artifact_root)

    @property
    def model_family(self) -> ModelFamily:
        """Declare the exact family accepted by this adapter."""
        return ModelFamily.RIDGE

    def train(self, job: TrainerJob) -> ModelArtifact:
        """Save baseline, every alpha result, and selected internal-test predictions."""
        if not job.folds or len(job.folds) != len(job.preprocessors):
            detail = "Ridge requires one verified preprocessor for every fold"
            raise RidgeTrainingError(detail)
        prepared = tuple(
            prepare_fold(job, fold, artifact)
            for fold, artifact in zip(job.folds, job.preprocessors, strict=True)
        )
        candidates = tuple(
            _evaluate_candidate(alpha, prepared) for alpha in job.experiment.ridge_alphas
        )
        selected = min(candidates, key=lambda item: (item.mean_validation_mse, item.alpha))
        fold_results, predictions, latest_model = _evaluate_selected(
            selected.alpha,
            prepared,
        )
        prediction_artifact = RidgePredictionArtifact(
            dataset_snapshot_id=job.experiment.dataset_snapshot_id,
            training_run_id=job.experiment.training_run_id,
            batches=predictions,
        )
        prediction_content = f"{prediction_artifact.model_dump_json()}\n".encode()
        prediction_sha = hashlib.sha256(prediction_content).hexdigest()
        lineage_payload = (
            f"{job.experiment.dataset_snapshot_id}|"
            f"{'|'.join(job.experiment.preprocessor_artifact_ids)}|{prediction_sha}|internal_test"
        )
        experiment_sha = hashlib.sha256(
            json.dumps(
                job.experiment.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        payload = RidgeArtifactPayload(
            training_run_id=job.experiment.training_run_id,
            dataset_snapshot_id=job.experiment.dataset_snapshot_id,
            schema_manifest_id=job.experiment.schema_manifest_id,
            lineage_manifest_id=job.experiment.lineage_manifest_id,
            experiment_manifest_sha256=experiment_sha,
            selected_alpha=selected.alpha,
            candidate_results=candidates,
            fold_results=fold_results,
            baseline_mean_validation_mse=float(
                np.mean([item.baseline_validation_mse for item in fold_results])
            ),
            internal_test_mean_mse=float(
                np.mean([item.internal_test_mse for item in fold_results])
            ),
            model_feature_names=model_feature_names(job.experiment.feature_names),
            coefficients=tuple(float(value) for value in latest_model.coef_),
            intercept=_intercept(latest_model.intercept_),
            preprocessor_artifact_ids=job.experiment.preprocessor_artifact_ids,
            prediction_artifact_sha256=prediction_sha,
            prediction_lineage_id=(
                f"prediction_lineage_{hashlib.sha256(lineage_payload.encode()).hexdigest()}"
            ),
            prediction_row_count=sum(item.internal_test_rows for item in fold_results),
            random_seed=job.experiment.random_seed,
            portfolio_rule_version=job.experiment.portfolio_rule_version,
            cost_rule_version=job.experiment.cost_rule_version,
            final_test_runs=0,
            model_status="DRAFT",
        )
        return self._store.write(payload, prediction_artifact)


def _evaluate_candidate(
    alpha: float,
    folds: tuple[PreparedFold, ...],
) -> RidgeCandidateResult:
    losses = tuple(
        _mse(
            fold.validation_y,
            _new_ridge(alpha).fit(fold.train_x, fold.train_y).predict(fold.validation_x),
        )
        for fold in folds
    )
    return RidgeCandidateResult(
        alpha=alpha,
        fold_validation_mse=losses,
        mean_validation_mse=float(np.mean(losses)),
    )


def _evaluate_selected(
    alpha: float,
    folds: tuple[PreparedFold, ...],
) -> tuple[tuple[RidgeFoldResult, ...], tuple[FoldPredictionBatch, ...], _TypedRidge]:
    results: list[RidgeFoldResult] = []
    predictions: list[FoldPredictionBatch] = []
    latest_model: _TypedRidge | None = None
    for fold in folds:
        model = _new_ridge(alpha).fit(fold.train_x, fold.train_y)
        validation_prediction = model.predict(fold.validation_x)
        test_prediction = model.predict(fold.test_x)
        baseline_prediction = np.mean(
            fold.validation_x[:, : fold.validation_x.shape[1] // 2], axis=1
        )
        results.append(
            RidgeFoldResult(
                fold_index=fold.fold_index,
                baseline_validation_mse=_mse(fold.validation_y, baseline_prediction),
                selected_validation_mse=_mse(fold.validation_y, validation_prediction),
                internal_test_mse=_mse(fold.test_y, test_prediction),
                internal_test_rows=len(fold.test_y),
            )
        )
        predictions.append(
            FoldPredictionBatch(
                fold_index=fold.fold_index,
                observation_keys_sha256=fold.test_keys_sha256,
                predictions=tuple(float(value) for value in test_prediction),
                labels=tuple(float(value) for value in fold.test_y),
            )
        )
        latest_model = model
    if latest_model is None:
        detail = "selected Ridge produced no fitted folds"
        raise RidgeTrainingError(detail)
    return tuple(results), tuple(predictions), latest_model


def _mse(actual: NDArray[np.float64], predicted: NDArray[np.float64]) -> float:
    return float(np.mean((actual - predicted) ** 2))


def _new_ridge(alpha: float) -> _TypedRidge:
    return Ridge(alpha=alpha)


def _intercept(value: float | NDArray[np.float64]) -> float:
    match value:
        case float() as scalar:
            return scalar
        case int() as integer:
            return float(integer)
        case np.ndarray() as array:
            return float(array.item())
