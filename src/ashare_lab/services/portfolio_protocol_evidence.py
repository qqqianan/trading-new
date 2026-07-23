"""Read and verify the exact evidence chain for a portfolio protocol."""

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
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
    DatasetSpecStoreError,
)
from ashare_lab.research.model_attribution.models import ModelPerformanceAttributionReport
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


class PortfolioProtocolEvidenceError(Exception):
    """A parent evidence artifact is missing, altered, or inconsistent."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable evidence blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the evidence boundary and concrete blocker."""
        return f"portfolio_protocol_evidence: {self.detail}"


@dataclass(frozen=True, slots=True)
class PortfolioProtocolEvidence:
    """Exact parent chain that must agree before protocol creation."""

    attribution: ModelPerformanceAttributionReport
    diagnostic: ModelDiagnosticReport
    model: RidgeExperimentArtifact
    dataset: DatasetSpec
    baseline_backtest: PortfolioBacktestReport
    model_backtest: PortfolioBacktestReport
    baseline_targets: PortfolioTargetBatch
    model_targets: PortfolioTargetBatch


def load_portfolio_protocol_evidence(
    root: Path,
    attribution_report_id: str,
) -> PortfolioProtocolEvidence:
    """Read exact content-addressed parents and fail closed on any mismatch."""
    try:
        attribution = _read_attribution(root, attribution_report_id)
        diagnostic = _read_diagnostic(root, attribution.diagnostic_report_id)
        model_store = RidgeArtifactStore(root)
        model = model_store.read(model_store.descriptor(attribution.model_id))
        dataset = _read_dataset(root)
        baseline = _read_backtest(root, attribution.baseline_backtest_id)
        model_backtest = _read_backtest(root, attribution.model_backtest_id)
        evidence = PortfolioProtocolEvidence(
            attribution=attribution,
            diagnostic=diagnostic,
            model=model,
            dataset=dataset,
            baseline_backtest=baseline,
            model_backtest=model_backtest,
            baseline_targets=_read_targets(root, baseline.target_artifact_id),
            model_targets=_read_targets(root, attribution.model_target_artifact_id),
        )
        _verify_evidence(evidence)
    except (
        ModelAttributionStoreError,
        ModelDiagnosticStoreError,
        RidgeArtifactStoreError,
        DatasetSpecStoreError,
        PortfolioBacktestReportStoreError,
        PortfolioTargetStoreError,
    ) as error:
        raise PortfolioProtocolEvidenceError(str(error)) from error
    else:
        return evidence


def _verify_evidence(evidence: PortfolioProtocolEvidence) -> None:
    attribution = evidence.attribution
    diagnostic = evidence.diagnostic
    model = evidence.model
    dataset = evidence.dataset
    baseline = evidence.baseline_backtest
    model_backtest = evidence.model_backtest
    if (
        attribution.dataset_snapshot_id != dataset.snapshot_id
        or diagnostic.dataset_snapshot_id != dataset.snapshot_id
        or model.dataset_snapshot_id != dataset.snapshot_id
        or attribution.model_id != model.model_id
        or diagnostic.model_id != model.model_id
        or attribution.prediction_artifact_sha256 != model.prediction_artifact_sha256
        or diagnostic.prediction_artifact_sha256 != model.prediction_artifact_sha256
        or attribution.model_target_artifact_id != model_backtest.target_artifact_id
        or attribution.baseline_backtest_id != diagnostic.portfolio.baseline_backtest_id
        or attribution.model_backtest_id != diagnostic.portfolio.model_backtest_id
        or baseline.dataset_snapshot_id != dataset.snapshot_id
        or model_backtest.dataset_snapshot_id != dataset.snapshot_id
        or baseline.factor_report_id != diagnostic.factor_report_id
        or model_backtest.factor_report_id != diagnostic.factor_report_id
        or baseline.model_id is not None
        or model_backtest.model_id != model.model_id
        or baseline.cost_rule_version != model_backtest.cost_rule_version
        or baseline.risk_rule_version != model_backtest.risk_rule_version
        or evidence.baseline_targets.model_id is not None
        or evidence.model_targets.model_id != model.model_id
        or evidence.baseline_targets.dataset_snapshot_id != dataset.snapshot_id
        or evidence.model_targets.dataset_snapshot_id != dataset.snapshot_id
        or attribution.tuning_permitted
        or attribution.final_test_runs != 0
        or any(item.final_test_runs != 0 for item in (baseline, model_backtest))
    ):
        detail = "attribution, model, dataset, targets, and backtest identities differ"
        raise PortfolioProtocolEvidenceError(detail)


def _read_attribution(root: Path, report_id: str) -> ModelPerformanceAttributionReport:
    path = root / "model_attributions" / report_id / "report.json"
    return ModelAttributionStore(root).read(
        ModelAttributionDescriptor(
            report_id=report_id,
            report_path=path,
            data_sha256=_sha256(path),
        )
    )


def _read_diagnostic(root: Path, report_id: str) -> ModelDiagnosticReport:
    path = root / "model_diagnostics" / report_id / "report.json"
    return ModelDiagnosticStore(root).read(
        ModelDiagnosticDescriptor(
            report_id=report_id,
            report_path=path,
            data_sha256=_sha256(path),
        )
    )


def _read_dataset(root: Path) -> DatasetSpec:
    paths = tuple((root / "dataset_spec").glob("ds_*/manifest.json"))
    if len(paths) != 1:
        detail = f"expected exactly one DatasetSpec, found {len(paths)}"
        raise PortfolioProtocolEvidenceError(detail)
    path = paths[0]
    return DatasetSpecStore(root).read(
        DatasetSpecDescriptor(
            snapshot_id=path.parent.name,
            manifest_path=path,
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
        raise PortfolioProtocolEvidenceError(detail) from error
