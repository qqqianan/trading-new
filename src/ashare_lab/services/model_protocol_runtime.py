"""Composition root for preregistering the next model experiment."""

import hashlib
from datetime import date, datetime
from pathlib import Path

from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
    PortfolioBacktestReportStoreError,
)
from ashare_lab.code_identity import CodeIdentityError, load_git_evidence
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
    DatasetSpecStoreError,
)
from ashare_lab.research.experiments.protocol_identity import (
    ModelProtocolRequest,
    create_rank_aligned_protocol,
)
from ashare_lab.research.experiments.protocol_store import (
    ModelProtocolDescriptor,
    ModelProtocolStore,
    ModelProtocolStoreError,
)
from ashare_lab.research.model_diagnostics.store import (
    ModelDiagnosticDescriptor,
    ModelDiagnosticStore,
    ModelDiagnosticStoreError,
)
from ashare_lab.research.splits.final_holdout import FinalHoldoutSpec
from ashare_lab.research.splits.walk_forward import DEVELOPMENT_END


class ModelProtocolRuntimeError(Exception):
    """Existing research evidence cannot freeze the next experiment protocol."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable preregistration blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"model_protocol_runtime: {self.detail}"


def run_default_model_preregistration(
    project_root: Path,
    diagnostic_report_id: str,
    registered_at: datetime,
    registered_by: str,
) -> ModelProtocolDescriptor:
    """Freeze a rank-aligned experiment without training or holdout access."""
    try:
        return _run_default_model_preregistration(
            project_root,
            diagnostic_report_id,
            registered_at,
            registered_by,
        )
    except (
        ModelDiagnosticStoreError,
        RidgeArtifactStoreError,
        DatasetSpecStoreError,
        PortfolioBacktestReportStoreError,
        CodeIdentityError,
        ModelProtocolStoreError,
    ) as error:
        raise ModelProtocolRuntimeError(str(error)) from error


def _run_default_model_preregistration(
    project_root: Path,
    diagnostic_report_id: str,
    registered_at: datetime,
    registered_by: str,
) -> ModelProtocolDescriptor:
    root = project_root / "data" / "artifacts"
    diagnostic_path = root / "model_diagnostics" / diagnostic_report_id / "report.json"
    diagnostic = ModelDiagnosticStore(root).read(
        ModelDiagnosticDescriptor(
            report_id=diagnostic_report_id,
            report_path=diagnostic_path,
            data_sha256=_sha256(diagnostic_path),
        )
    )
    model_store = RidgeArtifactStore(root)
    model_descriptor = model_store.descriptor(diagnostic.model_id)
    model = model_store.read(model_descriptor)
    dataset_path = _sole_path(root / "dataset_spec", "ds_*/manifest.json")
    dataset = DatasetSpecStore(root).read(
        DatasetSpecDescriptor(dataset_path.parent.name, dataset_path, _sha256(dataset_path))
    )
    backtest_path = (
        root / "portfolio_backtests" / diagnostic.portfolio.model_backtest_id / "report.json"
    )
    backtest = PortfolioBacktestReportStore(root).read(
        PortfolioBacktestReportDescriptor(
            report_id=diagnostic.portfolio.model_backtest_id,
            report_path=backtest_path,
            data_sha256=_sha256(backtest_path),
        )
    )
    if (
        diagnostic.dataset_snapshot_id != dataset.snapshot_id
        or model.dataset_snapshot_id != dataset.snapshot_id
        or backtest.dataset_snapshot_id != dataset.snapshot_id
        or diagnostic.model_id != model.model_id
        or backtest.model_id != model.model_id
        or backtest.factor_report_id != diagnostic.factor_report_id
        or backtest.final_test_runs != 0
    ):
        detail = "diagnostic, model, backtest, and DatasetSpec identities differ"
        raise ModelProtocolRuntimeError(detail)
    if (
        diagnostic.diagnostic_scope != "POST_HOC_DEVELOPMENT_ONLY"
        or diagnostic.tuning_permitted
        or diagnostic.final_test_runs != 0
        or model.final_test_runs != 0
        or not model.training_feature_names
    ):
        detail = "diagnostic evidence cannot authorize preregistration"
        raise ModelProtocolRuntimeError(detail)
    holdout = FinalHoldoutSpec(
        dataset_snapshot_id=dataset.snapshot_id,
        development_end=DEVELOPMENT_END,
        holdout_start=date(2025, 1, 1),
        protocol_version="1.0.0",
    )
    protocol = create_rank_aligned_protocol(
        ModelProtocolRequest(
            dataset_snapshot_id=dataset.snapshot_id,
            schema_manifest_id=dataset.schema_manifest_id,
            lineage_manifest_id=dataset.lineage_manifest_id,
            parent_model_id=model.model_id,
            parent_diagnostic_report_id=diagnostic_report_id,
            registered_at=registered_at,
            registered_by=registered_by,
            code_commit=load_git_evidence(project_root).commit,
            rulebook_version=dataset.rulebook_version,
            feature_names=model.training_feature_names,
            label_name=dataset.label.name,
            cost_rule_version=backtest.cost_rule_version,
            risk_rule_version=backtest.risk_rule_version,
            holdout_spec_id=holdout.spec_id,
        )
    )
    return ModelProtocolStore(root).write(protocol)


def _sole_path(root: Path, pattern: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one DatasetSpec, found {len(paths)}"
        raise ModelProtocolRuntimeError(detail)
    return paths[0]


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise ModelProtocolRuntimeError(detail) from error
