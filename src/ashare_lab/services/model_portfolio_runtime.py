"""Composition root from one governed Ridge model to pre-risk portfolio targets."""

import hashlib
from pathlib import Path

from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
    PortfolioBacktestReportStoreError,
)
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.portfolio.builder import PortfolioConstructionError
from ashare_lab.portfolio.research_store import (
    PortfolioTargetDescriptor,
    PortfolioTargetStore,
    PortfolioTargetStoreError,
)
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
    DatasetSpecStoreError,
)
from ashare_lab.research.factors.report_store import (
    FactorReportDescriptor,
    FactorReportStore,
    FactorReportStoreError,
)
from ashare_lab.research.factors.runtime_frames import DiagnosticFrameAssemblyError
from ashare_lab.research.factors.runtime_source import FactorRuntimeSourceError
from ashare_lab.research.factors.selection import FactorDecisionStatus
from ashare_lab.research.preprocessing.fold import FoldPreprocessingError
from ashare_lab.research.preprocessing.store import FoldPreprocessorStoreError
from ashare_lab.research.splits.walk_forward import SplitIntegrityError
from ashare_lab.research.training.frame import TrainingFrameAssemblyError
from ashare_lab.services.factor_calendar_runtime import FactorCalendarRuntimeError
from ashare_lab.services.model_prediction import (
    RidgePredictionFrameError,
    build_ridge_prediction_score_frame,
)
from ashare_lab.services.portfolio_research import (
    ModelPortfolioBuildRequest,
    PortfolioResearchError,
    build_model_portfolio_targets,
)
from ashare_lab.services.ridge_portfolio_runtime import load_complete_ridge_portfolio_scores


class ModelPortfolioRuntimeError(Exception):
    """Model, research, or prediction identities cannot form portfolio targets."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed model-portfolio failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and blocker."""
        return f"model_portfolio_runtime: {self.detail}"


def run_default_model_portfolio(
    project_root: Path,
    model_id: str,
) -> PortfolioTargetDescriptor:
    """Verify a keyed DRAFT Ridge model and publish its development Top30 targets."""
    try:
        return _run_default_model_portfolio(project_root, model_id)
    except (
        RidgeArtifactStoreError,
        DatasetSpecStoreError,
        FactorReportStoreError,
        PortfolioBacktestReportStoreError,
        FactorCalendarRuntimeError,
        FactorRuntimeSourceError,
        DiagnosticFrameAssemblyError,
        FoldPreprocessingError,
        FoldPreprocessorStoreError,
        SplitIntegrityError,
        TrainingFrameAssemblyError,
        RidgePredictionFrameError,
        PortfolioResearchError,
        PortfolioConstructionError,
        PortfolioTargetStoreError,
    ) as error:
        raise ModelPortfolioRuntimeError(str(error)) from error


def _run_default_model_portfolio(
    project_root: Path,
    model_id: str,
) -> PortfolioTargetDescriptor:
    """Execute the verified composition after translating adapter failures."""
    artifact_root = project_root / "data" / "artifacts"
    model_store = RidgeArtifactStore(artifact_root)
    descriptor = model_store.descriptor(model_id)
    model = model_store.read(descriptor)
    predictions = model_store.read_predictions(descriptor)
    if (
        model.model_status != "DRAFT"
        or model.final_test_runs != 0
        or model.factor_report_id is None
        or model.trial_batch_id is None
        or model.source_portfolio_backtest_id is None
        or not model.training_feature_names
    ):
        detail = "model lacks complete governed development lineage"
        raise ModelPortfolioRuntimeError(detail)
    dataset_path = _sole_path(artifact_root / "dataset_spec", "ds_*/manifest.json")
    spec = DatasetSpecStore(artifact_root).read(
        DatasetSpecDescriptor(
            dataset_path.parent.name,
            dataset_path,
            _sha256(dataset_path),
        )
    )
    report_path = artifact_root / "factor_report" / model.factor_report_id / "report.json"
    report = FactorReportStore(artifact_root).read(
        FactorReportDescriptor(
            report_id=model.factor_report_id,
            report_path=report_path,
            data_sha256=_sha256(report_path),
        )
    )
    backtest_path = (
        artifact_root / "portfolio_backtests" / model.source_portfolio_backtest_id / "report.json"
    )
    backtest = PortfolioBacktestReportStore(artifact_root).read(
        PortfolioBacktestReportDescriptor(
            report_id=model.source_portfolio_backtest_id,
            report_path=backtest_path,
            data_sha256=_sha256(backtest_path),
        )
    )
    candidates = tuple(
        item.feature_name
        for item in report.decisions
        if item.status is FactorDecisionStatus.CANDIDATE
    )
    if (
        model.dataset_snapshot_id != spec.snapshot_id
        or predictions.dataset_snapshot_id != spec.snapshot_id
        or report.dataset_snapshot_id != spec.snapshot_id
        or report.batch_id != model.trial_batch_id
        or candidates != model.training_feature_names
        or backtest.dataset_snapshot_id != spec.snapshot_id
        or backtest.factor_report_id != model.factor_report_id
        or backtest.final_test_runs != 0
        or backtest.cost_rule_version != model.cost_rule_version
    ):
        detail = "model, report, source backtest, and DatasetSpec identities differ"
        raise ModelPortfolioRuntimeError(detail)
    scores = load_complete_ridge_portfolio_scores(
        project_root,
        spec,
        model,
        build_ridge_prediction_score_frame(predictions),
    )
    targets = build_model_portfolio_targets(
        ModelPortfolioBuildRequest(
            model_id=model.model_id,
            factor_report_id=model.factor_report_id,
            dataset_snapshot_id=model.dataset_snapshot_id,
            trial_batch_id=model.trial_batch_id,
        ),
        scores,
    )
    return PortfolioTargetStore(artifact_root).write(targets)


def _sole_path(root: Path, pattern: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one DatasetSpec, found {len(paths)}"
        raise ModelPortfolioRuntimeError(detail)
    return paths[0]


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise ModelPortfolioRuntimeError(detail) from error
