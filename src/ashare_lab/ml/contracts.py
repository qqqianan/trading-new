"""Framework-neutral contracts for governed model implementations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import polars as pl

from ashare_lab.research.experiments.manifest import ExperimentManifest, ModelFamily
from ashare_lab.research.preprocessing.models import FoldPreprocessingArtifact
from ashare_lab.research.splits.walk_forward import WalkForwardFold


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    """Immutable lineage and storage reference produced by a trainer."""

    model_id: str
    training_run_id: str
    dataset_snapshot_id: str
    artifact_uri: str
    artifact_sha256: str


@dataclass(frozen=True, slots=True)
class TrainerJob:
    """Verified development inputs passed only after governance approval."""

    experiment: ExperimentManifest
    folds: tuple[WalkForwardFold, ...]
    frame: pl.DataFrame
    preprocessors: tuple[FoldPreprocessingArtifact, ...]
    artifact_root: Path


class Trainer(Protocol):
    """Capability implemented by Ridge and future model adapters."""

    @property
    def model_family(self) -> ModelFamily:
        """Return the exact experiment family this adapter implements."""
        ...

    def train(self, job: TrainerJob) -> ModelArtifact:
        """Fit only from a service-created job containing verified artifacts."""
        ...
