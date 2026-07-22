"""Protocol-bound composition root for development-only rank Ridge training."""

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
    PortfolioBacktestReportStoreError,
)
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol
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
from ashare_lab.services.training import GovernedTrainingResult
from ashare_lab.services.training_runtime import run_protocol_rank_ridge_training
from ashare_lab.services.training_runtime_support import TrainingRuntimeError


class RankTrainingRuntimeError(Exception):
    """Frozen rank-model evidence cannot authorize development training."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable protocol-chain blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"rank_training_runtime: {self.detail}"


@dataclass(frozen=True, slots=True)
class RankTrainingRequest:
    """Verified parent research identities needed by the shared training runtime."""

    protocol: ModelExperimentProtocol
    factor_report_id: str
    portfolio_backtest_id: str

    @property
    def protocol_id(self) -> str:
        """Expose the verified content identity passed to the training manifest."""
        return self.protocol.protocol_id


def load_rank_training_request(project_root: Path, protocol_id: str) -> RankTrainingRequest:
    """Verify the preregistered parent chain before any training-frame read."""
    root = project_root / "data" / "artifacts"
    try:
        protocol_path = root / "model_protocols" / protocol_id / "manifest.json"
        protocol = ModelProtocolStore(root).read(
            ModelProtocolDescriptor(
                protocol_id=protocol_id,
                manifest_path=protocol_path,
                data_sha256=_sha256(protocol_path),
            )
        )
        model_store = RidgeArtifactStore(root)
        model = model_store.read(model_store.descriptor(protocol.parent_model_id))
        diagnostic_path = (
            root / "model_diagnostics" / protocol.parent_diagnostic_report_id / "report.json"
        )
        diagnostic = ModelDiagnosticStore(root).read(
            ModelDiagnosticDescriptor(
                report_id=protocol.parent_diagnostic_report_id,
                report_path=diagnostic_path,
                data_sha256=_sha256(diagnostic_path),
            )
        )
        baseline_id = model.source_portfolio_backtest_id
        if baseline_id is None:
            detail = "parent model has no baseline backtest"
            raise RankTrainingRuntimeError(detail)
        backtest_path = root / "portfolio_backtests" / baseline_id / "report.json"
        backtest = PortfolioBacktestReportStore(root).read(
            PortfolioBacktestReportDescriptor(
                report_id=baseline_id,
                report_path=backtest_path,
                data_sha256=_sha256(backtest_path),
            )
        )
    except (
        ModelProtocolStoreError,
        RidgeArtifactStoreError,
        ModelDiagnosticStoreError,
        PortfolioBacktestReportStoreError,
        OSError,
    ) as error:
        raise RankTrainingRuntimeError(str(error)) from error
    holdout = FinalHoldoutSpec(
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        development_end=DEVELOPMENT_END,
        holdout_start=date(2025, 1, 1),
        protocol_version="1.0.0",
    )
    if (
        model.model_id != protocol.parent_model_id
        or model.dataset_snapshot_id != protocol.dataset_snapshot_id
        or model.training_feature_names != protocol.feature_names
        or model.cost_rule_version != protocol.cost_rule_version
        or model.final_test_runs != 0
        or diagnostic.model_id != model.model_id
        or diagnostic.dataset_snapshot_id != protocol.dataset_snapshot_id
        or diagnostic.factor_report_id != model.factor_report_id
        or diagnostic.portfolio.baseline_backtest_id != baseline_id
        or diagnostic.diagnostic_scope != "POST_HOC_DEVELOPMENT_ONLY"
        or diagnostic.tuning_permitted
        or diagnostic.final_test_runs != 0
        or backtest.dataset_snapshot_id != protocol.dataset_snapshot_id
        or backtest.factor_report_id != model.factor_report_id
        or backtest.cost_rule_version != protocol.cost_rule_version
        or backtest.risk_rule_version != protocol.risk_rule_version
        or backtest.final_test_runs != 0
        or protocol.final_holdout.holdout_spec_id != holdout.spec_id
    ):
        detail = "protocol, parent model, diagnostic, and backtest identities differ"
        raise RankTrainingRuntimeError(detail)
    factor_report_id = model.factor_report_id
    if factor_report_id is None:
        detail = "parent model has no factor report"
        raise RankTrainingRuntimeError(detail)
    return RankTrainingRequest(protocol, factor_report_id, baseline_id)


def run_default_rank_ridge_training(
    project_root: Path,
    protocol_id: str,
) -> GovernedTrainingResult:
    """Train one protocol-bound rank Ridge candidate on development data only."""
    request = load_rank_training_request(project_root, protocol_id)
    try:
        return run_protocol_rank_ridge_training(
            project_root,
            request.factor_report_id,
            request.portfolio_backtest_id,
            request.protocol,
        )
    except TrainingRuntimeError as error:
        raise RankTrainingRuntimeError(error.detail) from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
