"""Verified Parquet source for fold-local development factor diagnostics."""

from datetime import date
from pathlib import Path
from typing import Protocol

import polars as pl

from ashare_lab.research.artifacts import ArtifactKind, ResearchSchemaCatalog
from ashare_lab.research.artifacts.artifact_identity import artifact_descriptor
from ashare_lab.research.artifacts.artifact_io import load_manifest
from ashare_lab.research.artifacts.parquet_store import ParquetArtifactStore
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.factors.runtime_frames import (
    DiagnosticFrameInputs,
    build_oos_diagnostic_frame,
)
from ashare_lab.research.splits.walk_forward import build_development_folds

_DEVELOPMENT_END = date(2024, 12, 31)
_SIZE_FEATURE = "log_total_mv"


class FactorRuntimeSourceError(Exception):
    """Frozen artifacts do not match the registered factor trial."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed runtime source failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the artifact source boundary and stable detail."""
        return f"factor_runtime_source: {self.detail}"


class ArtifactFrameReader(Protocol):
    """Read one artifact only after immutable evidence verification."""

    def read(self, kind: ArtifactKind, artifact_id: str) -> pl.DataFrame:
        """Return governed rows for one physical kind and identity."""
        ...


class VerifiedArtifactFrameReader:
    """Verify local manifest, path, SHA-256, and exact row schema before reading."""

    def __init__(self, project_root: Path) -> None:
        """Bind the registered schema catalog and artifact root."""
        schema_paths = tuple(sorted((project_root / "schemas").glob("research_*_row_v1.json")))
        self._artifact_root = project_root / "data" / "artifacts"
        self._store = ParquetArtifactStore(
            self._artifact_root,
            ResearchSchemaCatalog.load(schema_paths),
        )

    def read(self, kind: ArtifactKind, artifact_id: str) -> pl.DataFrame:
        """Verify and return one immutable Parquet payload."""
        directory = self._artifact_root / kind.value / artifact_id
        manifest = load_manifest(directory / "manifest.json")
        return self._store.read(artifact_descriptor(directory, manifest))


class ArtifactFactorFrameSource:
    """Load one verified factor at a time while sharing label, size, and universe rows."""

    def __init__(
        self,
        reader: ArtifactFrameReader,
        spec: DatasetSpec,
        development_calendar: tuple[date, ...],
    ) -> None:
        """Verify shared immutable artifacts and freeze development folds."""
        self._reader = reader
        self._spec = spec
        self._feature_ids = {
            item.name: artifact_id
            for item, artifact_id in zip(spec.features, spec.feature_artifact_ids, strict=True)
        }
        universe = self._development(reader.read(ArtifactKind.UNIVERSE, spec.universe_version))
        label = self._development(reader.read(ArtifactKind.LABEL, spec.label_artifact_id))
        size_id = self._feature_ids.get(_SIZE_FEATURE)
        if size_id is None:
            detail = "DatasetSpec does not contain the required log_total_mv feature"
            raise FactorRuntimeSourceError(detail)
        size = self._development(reader.read(ArtifactKind.FEATURE, size_id))
        dates = tuple(
            day
            for day in development_calendar
            if spec.start_date <= day <= min(spec.end_date, _DEVELOPMENT_END)
        )
        self._folds = build_development_folds(dates)
        if not self._folds:
            detail = "development artifact calendar cannot form the frozen walk-forward protocol"
            raise FactorRuntimeSourceError(detail)
        decisions = set(universe["decision_time"].dt.date().unique())
        missing_decisions = decisions.difference(dates)
        if missing_decisions:
            detail = "weekly artifact decision dates are absent from the governed calendar"
            raise FactorRuntimeSourceError(detail)
        self._universe = universe
        self._label = label
        self._size = size

    def load(self, trial: FactorTrial) -> pl.DataFrame:
        """Verify the trial artifact and return fold-local internal-test observations."""
        expected_id = self._feature_ids.get(trial.feature_name)
        if expected_id is None or expected_id != trial.feature_artifact_id:
            detail = f"trial feature artifact differs from DatasetSpec: {trial.feature_name}"
            raise FactorRuntimeSourceError(detail)
        feature = self._development(self._reader.read(ArtifactKind.FEATURE, expected_id))
        return build_oos_diagnostic_frame(
            DiagnosticFrameInputs(
                universe=self._universe,
                feature=feature,
                size=self._size,
                label=self._label,
            ),
            self._folds,
            feature_name=trial.feature_name,
            dataset_snapshot_id=self._spec.snapshot_id,
        )

    @staticmethod
    def _development(frame: pl.DataFrame) -> pl.DataFrame:
        return frame.filter(pl.col("decision_time").dt.date() <= _DEVELOPMENT_END)
