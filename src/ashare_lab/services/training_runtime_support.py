"""Shared identity and field-lineage helpers for governed training runtimes."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.research.artifacts.artifact_io import load_manifest
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.experiments.manifest import LabelTransform, ModelFamily
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol
from ashare_lab.research.factors.selection import FactorResearchReport
from ashare_lab.research.training.package import TrainingColumnSource


class TrainingRuntimeError(Exception):
    """Frozen real artifacts cannot complete governed Ridge training."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed composition-root failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"training_runtime: {self.detail}"


@dataclass(frozen=True, slots=True)
class ResearchTrainingChain:
    """Typed report sequence that must share one immutable research identity."""

    dataset_id: str
    factor_report_id: str
    candidates: tuple[str, ...]
    report: FactorResearchReport
    targets: PortfolioTargetBatch
    backtest: PortfolioBacktestReport


@dataclass(frozen=True, slots=True)
class TrainingVariant:
    """Model objective and optional frozen protocol for one shared data runtime."""

    model_family: ModelFamily
    label_transform: LabelTransform
    protocol: ModelExperimentProtocol | None


def training_column_sources(
    artifact_root: Path,
    spec: DatasetSpec,
    candidates: tuple[str, ...],
) -> tuple[TrainingColumnSource, ...]:
    """Bind every physical training column to its committed artifact schema."""
    feature_index = {
        feature.name: artifact_id
        for feature, artifact_id in zip(spec.features, spec.feature_artifact_ids, strict=True)
    }
    universe_schema = load_manifest(
        artifact_root / "universe" / spec.universe_version / "manifest.json"
    ).schema_manifest_id
    feature_sources = tuple(
        TrainingColumnSource(
            name,
            feature_index[name],
            load_manifest(
                artifact_root / "feature" / feature_index[name] / "manifest.json"
            ).schema_manifest_id,
        )
        for name in candidates
    )
    label_schema = load_manifest(
        artifact_root / "label" / spec.label_artifact_id / "manifest.json"
    ).schema_manifest_id
    return (
        TrainingColumnSource("decision_time", spec.universe_version, universe_schema),
        TrainingColumnSource("symbol", spec.universe_version, universe_schema),
        *feature_sources,
        TrainingColumnSource(spec.label.name, spec.label_artifact_id, label_schema),
    )


def verify_research_training_chain(chain: ResearchTrainingChain) -> None:
    """Reject report, target, or backtest identities from another research chain."""
    if (
        chain.report.dataset_snapshot_id != chain.dataset_id
        or chain.targets.dataset_snapshot_id != chain.dataset_id
        or chain.backtest.dataset_snapshot_id != chain.dataset_id
        or chain.targets.factor_report_id != chain.factor_report_id
        or chain.backtest.factor_report_id != chain.factor_report_id
        or chain.targets.trial_batch_id != chain.report.batch_id
        or chain.targets.candidate_factor_names != chain.candidates
        or chain.backtest.final_test_runs != 0
    ):
        detail = "factor report, portfolio, backtest, and DatasetSpec identities differ"
        raise TrainingRuntimeError(detail)


def sole_artifact_path(root: Path, pattern: str) -> Path:
    """Require one unambiguous content-addressed artifact path."""
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one DatasetSpec, found {len(paths)}"
        raise TrainingRuntimeError(detail)
    return paths[0]


def artifact_sha256(path: Path) -> str:
    """Hash one artifact or translate its missing-file error at the runtime boundary."""
    try:
        content = path.read_bytes()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise TrainingRuntimeError(detail) from error
    return hashlib.sha256(content).hexdigest()
