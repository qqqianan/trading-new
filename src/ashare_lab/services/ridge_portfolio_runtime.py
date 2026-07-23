"""Label-free artifact assembly for complete fold-local Ridge portfolio scores."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import polars as pl

from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.preprocessing.models import (
    FoldPreprocessingArtifact,
    FoldPreprocessorDescriptor,
)
from ashare_lab.research.preprocessing.store import FoldPreprocessorStore
from ashare_lab.research.splits.walk_forward import WalkForwardFold
from ashare_lab.research.training.frame import (
    TrainingFeatureFrame,
    assemble_development_feature_frame,
)
from ashare_lab.services.model_prediction import (
    RidgePredictionFrameError,
    build_complete_ridge_score_frame,
)


class VerifiedFrameReader(Protocol):
    """Narrow reader capability required by portfolio score assembly."""

    def read(self, kind: ArtifactKind, artifact_id: str) -> pl.DataFrame:
        """Return one verified artifact frame."""
        ...


@dataclass(frozen=True, slots=True)
class CompleteRidgeScoreRequest:
    """Exact model and data identities admitted to label-free score assembly."""

    artifact_root: Path
    spec: DatasetSpec
    model: RidgeExperimentArtifact
    folds: tuple[WalkForwardFold, ...]


def assemble_complete_ridge_portfolio_scores(
    request: CompleteRidgeScoreRequest,
    reader: VerifiedFrameReader,
    anchor_scores: pl.DataFrame,
) -> pl.DataFrame:
    """Reconstruct full test scores from exact feature and model lineage."""
    model = request.model
    spec = request.spec
    preprocessors = _read_preprocessors(request.artifact_root, model)
    size_feature = preprocessors[0].size_feature_name
    feature_names = (
        model.training_feature_names
        if size_feature in model.training_feature_names
        else (*model.training_feature_names, size_feature)
    )
    feature_index = {
        feature.name: (feature.version, artifact_id)
        for feature, artifact_id in zip(spec.features, spec.feature_artifact_ids, strict=True)
    }
    if set(feature_names).difference(feature_index):
        detail = "Ridge score features are absent from DatasetSpec"
        raise RidgePredictionFrameError(detail)
    features = tuple(
        TrainingFeatureFrame(
            name=name,
            version=feature_index[name][0],
            artifact_id=feature_index[name][1],
            frame=reader.read(ArtifactKind.FEATURE, feature_index[name][1]),
        )
        for name in feature_names
    )
    frame = assemble_development_feature_frame(
        reader.read(ArtifactKind.UNIVERSE, spec.universe_version),
        features,
    )
    return build_complete_ridge_score_frame(
        model,
        request.folds,
        preprocessors,
        frame,
        anchor_scores,
    )


def _read_preprocessors(
    artifact_root: Path,
    model: RidgeExperimentArtifact,
) -> tuple[FoldPreprocessingArtifact, ...]:
    store = FoldPreprocessorStore(artifact_root)
    return tuple(
        store.read(
            FoldPreprocessorDescriptor(
                artifact_id=artifact_id,
                manifest_path=(artifact_root / "preprocessor" / artifact_id / "manifest.json"),
                data_sha256=_sha256(artifact_root / "preprocessor" / artifact_id / "manifest.json"),
            )
        )
        for artifact_id in model.preprocessor_artifact_ids
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
