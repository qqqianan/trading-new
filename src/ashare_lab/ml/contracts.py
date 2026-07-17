"""Framework-neutral contracts for future model implementations."""

from dataclasses import dataclass
from typing import Protocol

from ashare_lab.research.experiments.manifest import ExperimentManifest
from ashare_lab.research.splits.walk_forward import WalkForwardFold


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    """Immutable lineage and storage reference produced by a trainer."""

    model_id: str
    training_run_id: str
    dataset_snapshot_id: str
    artifact_uri: str
    artifact_sha256: str


class Trainer(Protocol):
    """Capability implemented by Ridge, LightGBM, and future trainers."""

    def train(
        self,
        manifest: ExperimentManifest,
        folds: tuple[WalkForwardFold, ...],
    ) -> ModelArtifact:
        """Train only through a versioned manifest and approved time folds."""
        ...
