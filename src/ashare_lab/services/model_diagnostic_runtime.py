"""Composition root for one governed post-hoc Ridge diagnostic report."""

import hashlib
from dataclasses import dataclass
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
from ashare_lab.research.model_diagnostics.calculations import (
    ModelDiagnosticError,
    ModelDiagnosticInput,
    diagnose_ridge_model,
)
from ashare_lab.research.model_diagnostics.portfolio import PortfolioDiagnosticError
from ashare_lab.research.model_diagnostics.store import (
    ModelDiagnosticDescriptor,
    ModelDiagnosticStore,
    ModelDiagnosticStoreError,
)
from ashare_lab.services.model_prediction import (
    RidgePredictionFrameError,
    build_ridge_prediction_evaluation_frame,
)


class ModelDiagnosticRuntimeError(Exception):
    """Frozen model evidence cannot form one post-hoc diagnostic report."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable runtime blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"model_diagnostic_runtime: {self.detail}"


@dataclass(frozen=True, slots=True)
class ModelDiagnosticRuntimeChain:
    """Identities that must agree before diagnostic calculations begin."""

    model: RidgeExperimentArtifact
    prediction_run_id: str
    baseline_backtest: PortfolioBacktestReport
    model_backtest: PortfolioBacktestReport
    baseline_targets: PortfolioTargetBatch
    model_targets: PortfolioTargetBatch


def run_default_model_diagnostics(
    project_root: Path,
    model_id: str,
    model_backtest_id: str,
) -> ModelDiagnosticDescriptor:
    """Verify one Ridge research chain and publish its immutable diagnosis."""
    try:
        return _run_default_model_diagnostics(project_root, model_id, model_backtest_id)
    except (
        RidgeArtifactStoreError,
        PortfolioTargetStoreError,
        PortfolioBacktestReportStoreError,
        RidgePredictionFrameError,
        ModelDiagnosticError,
        PortfolioDiagnosticError,
        ModelDiagnosticStoreError,
    ) as error:
        raise ModelDiagnosticRuntimeError(str(error)) from error


def _run_default_model_diagnostics(
    project_root: Path,
    model_id: str,
    model_backtest_id: str,
) -> ModelDiagnosticDescriptor:
    artifact_root = project_root / "data" / "artifacts"
    model_store = RidgeArtifactStore(artifact_root)
    descriptor = model_store.descriptor(model_id)
    model = model_store.read(descriptor)
    predictions = model_store.read_predictions(descriptor)
    baseline_id = _baseline_id(model)
    baseline_backtest = _read_backtest(artifact_root, baseline_id)
    model_backtest = _read_backtest(artifact_root, model_backtest_id)
    baseline_targets = _read_targets(artifact_root, baseline_backtest.target_artifact_id)
    model_targets = _read_targets(artifact_root, model_backtest.target_artifact_id)
    _verify_chain(
        ModelDiagnosticRuntimeChain(
            model,
            predictions.training_run_id,
            baseline_backtest,
            model_backtest,
            baseline_targets,
            model_targets,
        )
    )
    report = diagnose_ridge_model(
        ModelDiagnosticInput(
            model=model,
            predictions=build_ridge_prediction_evaluation_frame(predictions),
            baseline_targets=baseline_targets,
            model_targets=model_targets,
            baseline_backtest_id=baseline_id,
            baseline_backtest=baseline_backtest,
            model_backtest_id=model_backtest_id,
            model_backtest=model_backtest,
        )
    )
    return ModelDiagnosticStore(artifact_root).write(report)


def _verify_chain(chain: ModelDiagnosticRuntimeChain) -> None:
    model = chain.model
    factor_report_id = model.factor_report_id
    if (
        factor_report_id is None
        or chain.prediction_run_id != model.training_run_id
        or chain.baseline_backtest.factor_report_id != factor_report_id
        or chain.model_backtest.factor_report_id != factor_report_id
        or chain.baseline_targets.factor_report_id != factor_report_id
        or chain.model_targets.factor_report_id != factor_report_id
        or chain.baseline_backtest.cost_rule_version != model.cost_rule_version
        or chain.baseline_backtest.cost_rule_version != chain.model_backtest.cost_rule_version
        or chain.baseline_backtest.risk_rule_version != chain.model_backtest.risk_rule_version
        or chain.baseline_targets.portfolio_rule_version != model.portfolio_rule_version
        or chain.model_targets.portfolio_rule_version != "2.0.0"
    ):
        detail = "model, predictions, targets, or governed comparison rules differ"
        raise ModelDiagnosticRuntimeError(detail)


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


def _baseline_id(model: RidgeExperimentArtifact) -> str:
    if model.source_portfolio_backtest_id is None:
        detail = "model source baseline backtest is absent"
        raise ModelDiagnosticRuntimeError(detail)
    return model.source_portfolio_backtest_id


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise ModelDiagnosticRuntimeError(detail) from error
