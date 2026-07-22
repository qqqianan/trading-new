from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
)
from ashare_lab.code_identity import GitEvidence
from ashare_lab.ml.contracts import ModelArtifact
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.research.experiments.protocol_store import ModelProtocolStore
from ashare_lab.research.model_diagnostics.models import (
    BacktestComparison,
    ModelDiagnosticReport,
)
from ashare_lab.research.model_diagnostics.store import (
    ModelDiagnosticDescriptor,
    ModelDiagnosticStore,
)
from ashare_lab.services import model_protocol_runtime
from ashare_lab.services.model_protocol_runtime import (
    ModelProtocolRuntimeError,
    run_default_model_preregistration,
)

from .test_portfolio_backtest_store import portfolio_report_fixture
from .training_support import build_training_evidence, training_frame

MODEL_ID = "ridge_model_" + "a" * 64
DIAGNOSTIC_ID = "model_diagnostic_" + "b" * 64
BACKTEST_ID = "portfolio_backtest_" + "c" * 64


def test_model_protocol_runtime_verifies_parent_chain_before_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: exact diagnostic, parent model, DatasetSpec, and governed model backtest evidence.
    root = tmp_path / "data" / "artifacts"
    _evidence, experiment = build_training_evidence(root, training_frame())
    diagnostic = ModelDiagnosticReport.model_construct(
        model_id=MODEL_ID,
        dataset_snapshot_id=experiment.dataset_snapshot_id,
        factor_report_id=experiment.factor_report_id,
        diagnostic_scope="POST_HOC_DEVELOPMENT_ONLY",
        tuning_permitted=False,
        final_test_runs=0,
        portfolio=BacktestComparison.model_construct(model_backtest_id=BACKTEST_ID),
    )
    model = RidgeExperimentArtifact.model_construct(
        model_id=MODEL_ID,
        dataset_snapshot_id=experiment.dataset_snapshot_id,
        final_test_runs=0,
        training_feature_names=experiment.feature_names,
    )
    backtest = portfolio_report_fixture().model_copy(
        update={
            "model_id": MODEL_ID,
            "dataset_snapshot_id": experiment.dataset_snapshot_id,
            "factor_report_id": experiment.factor_report_id,
            "final_test_runs": 0,
        }
    )
    diagnostic_path = root / "model_diagnostics" / DIAGNOSTIC_ID / "report.json"
    backtest_path = root / "portfolio_backtests" / BACKTEST_ID / "report.json"
    for path in (diagnostic_path, backtest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    def read_diagnostic(
        _store: ModelDiagnosticStore,
        _descriptor: ModelDiagnosticDescriptor,
    ) -> ModelDiagnosticReport:
        return diagnostic

    def model_descriptor(_store: RidgeArtifactStore, _model_id: str) -> ModelArtifact:
        return ModelArtifact(
            MODEL_ID,
            "ridge_run_test",
            experiment.dataset_snapshot_id,
            str(root / "model.json"),
            "d" * 64,
        )

    def read_model(
        _store: RidgeArtifactStore,
        _descriptor: ModelArtifact,
    ) -> RidgeExperimentArtifact:
        return model

    def read_backtest(
        _store: PortfolioBacktestReportStore,
        _descriptor: PortfolioBacktestReportDescriptor,
    ) -> PortfolioBacktestReport:
        return backtest

    monkeypatch.setattr(ModelDiagnosticStore, "read", read_diagnostic)
    monkeypatch.setattr(RidgeArtifactStore, "descriptor", model_descriptor)
    monkeypatch.setattr(RidgeArtifactStore, "read", read_model)
    monkeypatch.setattr(PortfolioBacktestReportStore, "read", read_backtest)

    def git_evidence(_root: Path) -> GitEvidence:
        return GitEvidence(commit="e" * 40, is_clean=True)

    monkeypatch.setattr(model_protocol_runtime, "load_git_evidence", git_evidence)

    # When: the formal preregistration root freezes the next experiment.
    descriptor = run_default_model_preregistration(
        tmp_path,
        DIAGNOSTIC_ID,
        datetime(2026, 7, 20, 19, tzinfo=ZoneInfo("Asia/Shanghai")),
        "research_owner",
    )

    # Then: the protocol binds parent evidence and performs no training or holdout access.
    protocol = ModelProtocolStore(root).read(descriptor)
    assert protocol.parent_model_id == MODEL_ID
    assert protocol.parent_diagnostic_report_id == DIAGNOSTIC_ID
    assert protocol.code_commit == "e" * 40
    assert protocol.status == "PREREGISTERED_NOT_IMPLEMENTED"
    assert not (tmp_path / "data" / "governance" / "final_holdout_access").exists()


def test_model_protocol_runtime_translates_missing_diagnostic_to_stable_blocker(
    tmp_path: Path,
) -> None:
    # Given: an artifact root without the requested diagnostic identity.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: preregistration stops before model or holdout access.
    with pytest.raises(ModelProtocolRuntimeError, match="model_protocol_runtime"):
        run_default_model_preregistration(
            tmp_path,
            DIAGNOSTIC_ID,
            datetime(2026, 7, 20, 19, tzinfo=ZoneInfo("Asia/Shanghai")),
            "research_owner",
        )
