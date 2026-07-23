"""Composition root for governed model portfolio performance attribution."""

import hashlib
from pathlib import Path

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
    PortfolioBacktestReportStoreError,
)
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.portfolio.research_store import (
    PortfolioTargetDescriptor,
    PortfolioTargetStore,
    PortfolioTargetStoreError,
)
from ashare_lab.research.model_attribution.calculations import (
    ModelAttributionError,
    ModelAttributionInput,
    attribute_model_portfolio,
)
from ashare_lab.research.model_attribution.portfolio import PortfolioAttributionError
from ashare_lab.research.model_attribution.store import (
    ModelAttributionDescriptor,
    ModelAttributionStore,
    ModelAttributionStoreError,
)
from ashare_lab.research.model_diagnostics.models import ModelDiagnosticReport
from ashare_lab.research.model_diagnostics.store import (
    ModelDiagnosticDescriptor,
    ModelDiagnosticStore,
    ModelDiagnosticStoreError,
)
from ashare_lab.services.model_prediction import (
    RidgePredictionFrameError,
    build_ridge_prediction_evaluation_frame,
)


class ModelAttributionRuntimeError(Exception):
    """Frozen model evidence cannot form one governed attribution report."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable runtime blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"model_attribution_runtime: {self.detail}"


def run_model_performance_attribution(
    project_root: Path,
    diagnostic_report_id: str,
) -> ModelAttributionDescriptor:
    """Resolve one exact diagnosis chain and publish immutable attribution."""
    try:
        return _run_model_performance_attribution(project_root, diagnostic_report_id)
    except (
        ModelDiagnosticStoreError,
        RidgeArtifactStoreError,
        PortfolioBacktestReportStoreError,
        PortfolioTargetStoreError,
        RidgePredictionFrameError,
        ModelAttributionError,
        PortfolioAttributionError,
        ModelAttributionStoreError,
    ) as error:
        raise ModelAttributionRuntimeError(str(error)) from error


def _run_model_performance_attribution(
    project_root: Path,
    diagnostic_report_id: str,
) -> ModelAttributionDescriptor:
    root = project_root / "data" / "artifacts"
    diagnostic = _read_diagnostic(root, diagnostic_report_id)
    model_store = RidgeArtifactStore(root)
    model_descriptor = model_store.descriptor(diagnostic.model_id)
    model = model_store.read(model_descriptor)
    predictions = build_ridge_prediction_evaluation_frame(
        model_store.read_predictions(model_descriptor)
    )
    baseline = _read_backtest(root, diagnostic.portfolio.baseline_backtest_id)
    model_backtest = _read_backtest(root, diagnostic.portfolio.model_backtest_id)
    targets = _read_targets(root, model_backtest.target_artifact_id)
    _verify_parent_chain(diagnostic_report_id, diagnostic, model, model_backtest, targets)
    report = attribute_model_portfolio(
        ModelAttributionInput(
            diagnostic_report_id=diagnostic_report_id,
            model=model,
            predictions=predictions,
            model_targets=targets,
            baseline_backtest_id=diagnostic.portfolio.baseline_backtest_id,
            baseline_backtest=baseline,
            model_backtest_id=diagnostic.portfolio.model_backtest_id,
            model_backtest=model_backtest,
        )
    )
    return ModelAttributionStore(root).write(report)


def _verify_parent_chain(
    diagnostic_report_id: str,
    diagnostic: ModelDiagnosticReport,
    model: RidgeExperimentArtifact,
    model_backtest: PortfolioBacktestReport,
    targets: PortfolioTargetBatch,
) -> None:
    if (
        not diagnostic_report_id.startswith("model_diagnostic_")
        or diagnostic.diagnostic_scope != "POST_HOC_DEVELOPMENT_ONLY"
        or diagnostic.tuning_permitted
        or diagnostic.final_test_runs != 0
        or diagnostic.model_id != model.model_id
        or diagnostic.dataset_snapshot_id != model.dataset_snapshot_id
        or diagnostic.prediction_artifact_sha256 != model.prediction_artifact_sha256
        or model_backtest.model_id != diagnostic.model_id
        or targets.model_id != diagnostic.model_id
    ):
        detail = "parent diagnosis, model backtest, and target identities differ"
        raise ModelAttributionRuntimeError(detail)


def _read_diagnostic(root: Path, report_id: str) -> ModelDiagnosticReport:
    path = root / "model_diagnostics" / report_id / "report.json"
    return ModelDiagnosticStore(root).read(
        ModelDiagnosticDescriptor(
            report_id=report_id,
            report_path=path,
            data_sha256=_sha256(path),
        )
    )


def _read_backtest(root: Path, report_id: str) -> PortfolioBacktestReport:
    path = root / "portfolio_backtests" / report_id / "report.json"
    return PortfolioBacktestReportStore(root).read(
        PortfolioBacktestReportDescriptor(
            report_id=report_id,
            report_path=path,
            data_sha256=_sha256(path),
        )
    )


def _read_targets(root: Path, artifact_id: str) -> PortfolioTargetBatch:
    path = root / "portfolio_targets" / artifact_id / "targets.json"
    return PortfolioTargetStore(root).read(
        PortfolioTargetDescriptor(
            artifact_id=artifact_id,
            artifact_path=path,
            data_sha256=_sha256(path),
        )
    )


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise ModelAttributionRuntimeError(detail) from error
