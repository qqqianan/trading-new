"""Composition root for governed real development Ridge training."""

from pathlib import Path

from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
)
from ashare_lab.code_identity import load_git_evidence
from ashare_lab.ml.trainers.ridge import RidgeRankTrainer, RidgeTrainer
from ashare_lab.portfolio.research_store import PortfolioTargetDescriptor, PortfolioTargetStore
from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
)
from ashare_lab.research.experiments.manifest import LabelTransform, ModelFamily
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol
from ashare_lab.research.factors.report_store import FactorReportDescriptor, FactorReportStore
from ashare_lab.research.factors.runtime_source import VerifiedArtifactFrameReader
from ashare_lab.research.factors.selection import FactorDecisionStatus
from ashare_lab.research.splits.walk_forward import build_development_folds
from ashare_lab.research.training.frame import (
    TrainingFeatureFrame,
    assemble_development_training_frame,
)
from ashare_lab.research.training.package import TrainingPackageRequest, build_training_package
from ashare_lab.services.factor_calendar_runtime import load_dataset_development_calendar
from ashare_lab.services.training import GovernedTrainingResult, TrainingService
from ashare_lab.services.training_runtime_support import (
    ResearchTrainingChain,
    TrainingRuntimeError,
    TrainingVariant,
    artifact_sha256,
    sole_artifact_path,
    training_column_sources,
    verify_research_training_chain,
)


def run_default_ridge_training(
    project_root: Path,
    factor_report_id: str,
    portfolio_backtest_id: str,
) -> GovernedTrainingResult:
    """Verify selected research evidence and fit one reproducible DRAFT Ridge model."""
    return _run_governed_ridge_training(
        project_root,
        factor_report_id,
        portfolio_backtest_id,
        TrainingVariant(ModelFamily.RIDGE, LabelTransform.IDENTITY, None),
    )


def run_protocol_rank_ridge_training(
    project_root: Path,
    factor_report_id: str,
    portfolio_backtest_id: str,
    protocol: ModelExperimentProtocol,
) -> GovernedTrainingResult:
    """Fit rank-label Ridge only after a runtime has verified its frozen protocol."""
    return _run_governed_ridge_training(
        project_root,
        factor_report_id,
        portfolio_backtest_id,
        TrainingVariant(
            ModelFamily.RIDGE_RANK,
            LabelTransform.CROSS_SECTIONAL_PERCENTILE_RANK,
            protocol,
        ),
    )


def _run_governed_ridge_training(
    project_root: Path,
    factor_report_id: str,
    portfolio_backtest_id: str,
    variant: TrainingVariant,
) -> GovernedTrainingResult:
    artifact_root = project_root / "data" / "artifacts"
    dataset_path = sole_artifact_path(artifact_root / "dataset_spec", "ds_*/manifest.json")
    dataset_descriptor = DatasetSpecDescriptor(
        snapshot_id=dataset_path.parent.name,
        manifest_path=dataset_path,
        data_sha256=artifact_sha256(dataset_path),
    )
    spec = DatasetSpecStore(artifact_root).read(dataset_descriptor)
    report_path = artifact_root / "factor_report" / factor_report_id / "report.json"
    report = FactorReportStore(artifact_root).read(
        FactorReportDescriptor(
            report_id=factor_report_id,
            report_path=report_path,
            data_sha256=artifact_sha256(report_path),
        )
    )
    backtest_path = artifact_root / "portfolio_backtests" / portfolio_backtest_id / "report.json"
    backtest = PortfolioBacktestReportStore(artifact_root).read(
        PortfolioBacktestReportDescriptor(
            report_id=portfolio_backtest_id,
            report_path=backtest_path,
            data_sha256=artifact_sha256(backtest_path),
        )
    )
    target_path = artifact_root / "portfolio_targets" / backtest.target_artifact_id / "targets.json"
    targets = PortfolioTargetStore(artifact_root).read(
        PortfolioTargetDescriptor(
            artifact_id=backtest.target_artifact_id,
            artifact_path=target_path,
            data_sha256=artifact_sha256(target_path),
        )
    )
    candidates = tuple(
        item.feature_name
        for item in report.decisions
        if item.status is FactorDecisionStatus.CANDIDATE
    )
    verify_research_training_chain(
        ResearchTrainingChain(
            spec.snapshot_id,
            factor_report_id,
            candidates,
            report,
            targets,
            backtest,
        )
    )
    protocol = variant.protocol
    if protocol is not None and (
        protocol.dataset_snapshot_id != spec.snapshot_id
        or protocol.schema_manifest_id != spec.schema_manifest_id
        or protocol.lineage_manifest_id != spec.lineage_manifest_id
        or protocol.feature_names != candidates
        or protocol.label_name != spec.label.name
        or protocol.cost_rule_version != backtest.cost_rule_version
        or protocol.risk_rule_version != backtest.risk_rule_version
    ):
        detail = "rank protocol differs from the physical training research chain"
        raise TrainingRuntimeError(detail)
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
            column_sources=training_column_sources(artifact_root, spec, candidates),
            git_commit=load_git_evidence(project_root).commit,
            trial_batch_id=report.batch_id,
            factor_report_id=factor_report_id,
            portfolio_backtest_id=portfolio_backtest_id,
            portfolio_rule_version=(
                targets.portfolio_rule_version
                if protocol is None
                else protocol.portfolio_rule_version
            ),
            cost_rule_version=backtest.cost_rule_version,
            model_family=variant.model_family,
            label_transform=variant.label_transform,
            experiment_protocol_id=None if protocol is None else protocol.protocol_id,
        ),
        folds,
        frame,
    )
    match variant.model_family:
        case ModelFamily.RIDGE:
            trainer = RidgeTrainer(artifact_root)
        case ModelFamily.RIDGE_RANK:
            trainer = RidgeRankTrainer(artifact_root)
        case ModelFamily.LIGHTGBM_RANKER:
            detail = "LightGBM is not implemented"
            raise TrainingRuntimeError(detail)
    return TrainingService(trainer).train(
        package.evidence,
        package.experiment,
        folds,
        frame,
    )
