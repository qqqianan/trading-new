"""Composition root for governed real development Ridge training."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
)
from ashare_lab.code_identity import load_git_evidence
from ashare_lab.ml.trainers.ridge import RidgeTrainer
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.portfolio.research_store import PortfolioTargetDescriptor, PortfolioTargetStore
from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.artifacts.artifact_io import load_manifest
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
)
from ashare_lab.research.factors.report_store import FactorReportDescriptor, FactorReportStore
from ashare_lab.research.factors.runtime_source import VerifiedArtifactFrameReader
from ashare_lab.research.factors.selection import (
    FactorDecisionStatus,
    FactorResearchReport,
)
from ashare_lab.research.splits.walk_forward import build_development_folds
from ashare_lab.research.training.frame import (
    TrainingFeatureFrame,
    assemble_development_training_frame,
)
from ashare_lab.research.training.package import (
    TrainingColumnSource,
    TrainingPackageRequest,
    build_training_package,
)
from ashare_lab.services.factor_calendar_runtime import load_dataset_development_calendar
from ashare_lab.services.training import GovernedTrainingResult, TrainingService


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


def run_default_ridge_training(
    project_root: Path,
    factor_report_id: str,
    portfolio_backtest_id: str,
) -> GovernedTrainingResult:
    """Verify selected research evidence and fit one reproducible DRAFT Ridge model."""
    artifact_root = project_root / "data" / "artifacts"
    dataset_path = _sole_path(artifact_root / "dataset_spec", "ds_*/manifest.json")
    dataset_descriptor = DatasetSpecDescriptor(
        snapshot_id=dataset_path.parent.name,
        manifest_path=dataset_path,
        data_sha256=_sha256(dataset_path),
    )
    spec = DatasetSpecStore(artifact_root).read(dataset_descriptor)
    report_path = artifact_root / "factor_report" / factor_report_id / "report.json"
    report = FactorReportStore(artifact_root).read(
        FactorReportDescriptor(
            report_id=factor_report_id,
            report_path=report_path,
            data_sha256=_sha256(report_path),
        )
    )
    backtest_path = artifact_root / "portfolio_backtests" / portfolio_backtest_id / "report.json"
    backtest = PortfolioBacktestReportStore(artifact_root).read(
        PortfolioBacktestReportDescriptor(
            report_id=portfolio_backtest_id,
            report_path=backtest_path,
            data_sha256=_sha256(backtest_path),
        )
    )
    target_path = artifact_root / "portfolio_targets" / backtest.target_artifact_id / "targets.json"
    targets = PortfolioTargetStore(artifact_root).read(
        PortfolioTargetDescriptor(
            artifact_id=backtest.target_artifact_id,
            artifact_path=target_path,
            data_sha256=_sha256(target_path),
        )
    )
    candidates = tuple(
        item.feature_name
        for item in report.decisions
        if item.status is FactorDecisionStatus.CANDIDATE
    )
    _verify_research_chain(
        ResearchTrainingChain(
            spec.snapshot_id,
            factor_report_id,
            candidates,
            report,
            targets,
            backtest,
        )
    )
    feature_index = {
        feature.name: (feature.version, artifact_id)
        for feature, artifact_id in zip(spec.features, spec.feature_artifact_ids, strict=True)
    }
    missing_candidates = set(candidates).difference(feature_index)
    if not candidates or missing_candidates:
        detail = f"candidate features are absent from DatasetSpec: {sorted(missing_candidates)}"
        raise TrainingRuntimeError(detail)
    reader = VerifiedArtifactFrameReader(project_root)
    universe = reader.read(ArtifactKind.UNIVERSE, spec.universe_version)
    label = reader.read(ArtifactKind.LABEL, spec.label_artifact_id)
    feature_frames = tuple(
        TrainingFeatureFrame(
            name=name,
            version=feature_index[name][0],
            artifact_id=feature_index[name][1],
            frame=reader.read(ArtifactKind.FEATURE, feature_index[name][1]),
        )
        for name in candidates
    )
    frame = assemble_development_training_frame(
        universe,
        feature_frames,
        label,
        label_name=spec.label.name,
        label_version=spec.label.version,
    )
    calendar = load_dataset_development_calendar(project_root, spec)
    folds = build_development_folds(calendar)
    package = build_training_package(
        TrainingPackageRequest(
            artifact_root=artifact_root,
            holdout_ledger_root=project_root / "data" / "governance",
            dataset_descriptor=dataset_descriptor,
            dataset_spec=spec,
            feature_names=candidates,
            size_feature_name="log_total_mv",
            label_name=spec.label.name,
            label_version=spec.label.version,
            column_sources=_column_sources(artifact_root, spec, candidates),
            git_commit=load_git_evidence(project_root).commit,
            trial_batch_id=report.batch_id,
            factor_report_id=factor_report_id,
            portfolio_backtest_id=portfolio_backtest_id,
            portfolio_rule_version=targets.portfolio_rule_version,
            cost_rule_version=backtest.cost_rule_version,
        ),
        folds,
        frame,
    )
    return TrainingService(RidgeTrainer(artifact_root)).train(
        package.evidence,
        package.experiment,
        folds,
        frame,
    )


def _column_sources(
    artifact_root: Path,
    spec: DatasetSpec,
    candidates: tuple[str, ...],
) -> tuple[TrainingColumnSource, ...]:
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


def _verify_research_chain(chain: ResearchTrainingChain) -> None:
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


def _sole_path(root: Path, pattern: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one DatasetSpec, found {len(paths)}"
        raise TrainingRuntimeError(detail)
    return paths[0]


def _sha256(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise TrainingRuntimeError(detail) from error
    return hashlib.sha256(content).hexdigest()
