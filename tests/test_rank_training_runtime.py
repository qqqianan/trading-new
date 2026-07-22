from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import PortfolioBacktestReportStore
from ashare_lab.ml.contracts import ModelArtifact
from ashare_lab.ml.registry import (
    DatasetSnapshotId,
    ModelId,
    ModelRecord,
    ModelStatus,
    TrainingRunId,
)
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.research.experiments.protocol_identity import (
    ModelProtocolRequest,
    create_rank_aligned_protocol,
)
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol
from ashare_lab.research.experiments.protocol_store import ModelProtocolStore
from ashare_lab.research.model_diagnostics.models import (
    BacktestComparison,
    ModelDiagnosticReport,
)
from ashare_lab.research.model_diagnostics.store import ModelDiagnosticStore
from ashare_lab.research.model_governance import ApprovalScope, TrainingApproval
from ashare_lab.research.splits.final_holdout import FinalHoldoutSpec
from ashare_lab.research.splits.walk_forward import DEVELOPMENT_END
from ashare_lab.services import rank_training_runtime
from ashare_lab.services.rank_training_runtime import (
    RankTrainingRequest,
    RankTrainingRuntimeError,
    load_rank_training_request,
    run_default_rank_ridge_training,
)
from ashare_lab.services.training import GovernedTrainingResult
from ashare_lab.services.training_runtime_support import TrainingRuntimeError

from .test_portfolio_backtest_store import portfolio_report_fixture

MODEL_ID = "ridge_model_" + "a" * 64
DIAGNOSTIC_ID = "model_diagnostic_" + "b" * 64
FACTOR_REPORT_ID = "factor_report_" + "c" * 64
BACKTEST_ID = "portfolio_backtest_" + "d" * 64
DATASET_ID = "ds_abc123"
FEATURES = ("factor_a", "factor_b")


def _protocol() -> ModelExperimentProtocol:
    holdout = FinalHoldoutSpec(
        dataset_snapshot_id=DATASET_ID,
        development_end=DEVELOPMENT_END,
        holdout_start=date(2025, 1, 1),
        protocol_version="1.0.0",
    )
    return create_rank_aligned_protocol(
        ModelProtocolRequest(
            dataset_snapshot_id=DATASET_ID,
            schema_manifest_id="schema_" + "e" * 64,
            lineage_manifest_id="lineage_" + "f" * 64,
            parent_model_id=MODEL_ID,
            parent_diagnostic_report_id=DIAGNOSTIC_ID,
            registered_at=datetime(2026, 7, 22, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
            registered_by="research_owner",
            code_commit="1" * 40,
            rulebook_version="1.1.0",
            feature_names=FEATURES,
            label_name="relative_return_20d",
            cost_rule_version="china_a_cost_v1",
            risk_rule_version="portfolio_risk_v1",
            holdout_spec_id=holdout.spec_id,
        )
    )


def _write_protocol(root: Path) -> str:
    return ModelProtocolStore(root).write(_protocol()).protocol_id


def test_rank_training_runtime_verifies_protocol_parent_chain_before_frame_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one protocol whose parent model, diagnostic, and baseline backtest agree.
    root = tmp_path / "data" / "artifacts"
    protocol_id = _write_protocol(root)
    model = RidgeExperimentArtifact.model_construct(
        model_id=MODEL_ID,
        dataset_snapshot_id=DATASET_ID,
        training_feature_names=FEATURES,
        factor_report_id=FACTOR_REPORT_ID,
        source_portfolio_backtest_id=BACKTEST_ID,
        cost_rule_version="china_a_cost_v1",
        final_test_runs=0,
    )
    diagnostic = ModelDiagnosticReport.model_construct(
        model_id=MODEL_ID,
        dataset_snapshot_id=DATASET_ID,
        factor_report_id=FACTOR_REPORT_ID,
        diagnostic_scope="POST_HOC_DEVELOPMENT_ONLY",
        tuning_permitted=False,
        final_test_runs=0,
        portfolio=BacktestComparison.model_construct(baseline_backtest_id=BACKTEST_ID),
    )
    backtest = portfolio_report_fixture().model_copy(
        update={
            "dataset_snapshot_id": DATASET_ID,
            "factor_report_id": FACTOR_REPORT_ID,
            "cost_rule_version": "china_a_cost_v1",
            "risk_rule_version": "portfolio_risk_v1",
            "final_test_runs": 0,
        }
    )
    _mock_parent_reads(monkeypatch, root, model, diagnostic, backtest)

    # When: the rank runtime resolves the preregistered experiment.
    request = load_rank_training_request(tmp_path, protocol_id)

    # Then: only the exact original factor research chain is returned for training.
    assert request.factor_report_id == FACTOR_REPORT_ID
    assert request.portfolio_backtest_id == BACKTEST_ID
    assert request.protocol_id == protocol_id


def test_rank_training_runtime_rejects_parent_feature_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a protocol and parent model whose feature order was changed after diagnosis.
    root = tmp_path / "data" / "artifacts"
    protocol_id = _write_protocol(root)
    model = RidgeExperimentArtifact.model_construct(
        model_id=MODEL_ID,
        dataset_snapshot_id=DATASET_ID,
        training_feature_names=("factor_b", "factor_a"),
        factor_report_id=FACTOR_REPORT_ID,
        source_portfolio_backtest_id=BACKTEST_ID,
        cost_rule_version="china_a_cost_v1",
        final_test_runs=0,
    )
    diagnostic = ModelDiagnosticReport.model_construct(
        model_id=MODEL_ID,
        dataset_snapshot_id=DATASET_ID,
        factor_report_id=FACTOR_REPORT_ID,
        diagnostic_scope="POST_HOC_DEVELOPMENT_ONLY",
        tuning_permitted=False,
        final_test_runs=0,
        portfolio=BacktestComparison.model_construct(baseline_backtest_id=BACKTEST_ID),
    )
    backtest = portfolio_report_fixture().model_copy(
        update={
            "dataset_snapshot_id": DATASET_ID,
            "factor_report_id": FACTOR_REPORT_ID,
            "cost_rule_version": "china_a_cost_v1",
            "risk_rule_version": "portfolio_risk_v1",
            "final_test_runs": 0,
        }
    )
    _mock_parent_reads(monkeypatch, root, model, diagnostic, backtest)

    # When / Then: protocol drift is blocked before the shared training runtime runs.
    with pytest.raises(RankTrainingRuntimeError, match="identities differ"):
        load_rank_training_request(tmp_path, protocol_id)


def test_rank_training_runtime_blocks_missing_protocol_before_parent_reads(
    tmp_path: Path,
) -> None:
    # Given: an artifact root with no preregistered protocol bytes.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: the runtime translates missing evidence into one stable blocker.
    with pytest.raises(RankTrainingRuntimeError, match="rank_training_runtime"):
        load_rank_training_request(tmp_path, "model_protocol_" + "0" * 64)


def test_rank_training_runtime_delegates_only_verified_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a verified request and one governed DRAFT result from the shared runtime.
    protocol = _protocol()
    protocol_id = protocol.protocol_id
    request = RankTrainingRequest(protocol, FACTOR_REPORT_ID, BACKTEST_ID)
    artifact = ModelArtifact(
        "ridge_model_" + "9" * 64,
        "ridge_rank_run_test",
        DATASET_ID,
        "model.json",
        "8" * 64,
    )
    result = GovernedTrainingResult(
        artifact,
        TrainingApproval(
            approved=True,
            scope=ApprovalScope.DEVELOPMENT_TRAINING,
            rulebook_version="1.1.0",
            checks=(),
        ),
        ModelRecord(
            ModelId(artifact.model_id),
            DatasetSnapshotId(DATASET_ID),
            TrainingRunId(artifact.training_run_id),
            ModelStatus.DRAFT,
        ),
    )

    monkeypatch.setattr(rank_training_runtime, "load_rank_training_request", lambda *_: request)
    monkeypatch.setattr(
        rank_training_runtime, "run_protocol_rank_ridge_training", lambda *_: result
    )

    # When: the public rank runtime is invoked.
    actual = run_default_rank_ridge_training(tmp_path, protocol_id)

    # Then: it returns the sole TrainingService result without opening holdout state.
    assert actual == result
    assert not (tmp_path / "data" / "governance" / "final_holdout_access").exists()


def test_rank_training_runtime_requires_parent_baseline_backtest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid protocol whose parent model lost its source backtest identity.
    root = tmp_path / "data" / "artifacts"
    protocol_id = _write_protocol(root)
    model = RidgeExperimentArtifact.model_construct(
        model_id=MODEL_ID,
        dataset_snapshot_id=DATASET_ID,
        training_feature_names=FEATURES,
        factor_report_id=FACTOR_REPORT_ID,
        source_portfolio_backtest_id=None,
        cost_rule_version="china_a_cost_v1",
        final_test_runs=0,
    )
    diagnostic = ModelDiagnosticReport.model_construct()
    backtest = portfolio_report_fixture()
    _mock_parent_reads(monkeypatch, root, model, diagnostic, backtest)

    # When / Then: training stops before any training-frame artifact is read.
    with pytest.raises(RankTrainingRuntimeError, match="no baseline backtest"):
        load_rank_training_request(tmp_path, protocol_id)


def test_rank_training_runtime_translates_shared_runtime_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a verified protocol request whose physical training chain later drifts.
    protocol = _protocol()
    request = RankTrainingRequest(protocol, FACTOR_REPORT_ID, BACKTEST_ID)

    def reject(*_args: Path | str | ModelExperimentProtocol) -> GovernedTrainingResult:
        detail = "physical chain drift"
        raise TrainingRuntimeError(detail)

    monkeypatch.setattr(rank_training_runtime, "load_rank_training_request", lambda *_: request)
    monkeypatch.setattr(rank_training_runtime, "run_protocol_rank_ridge_training", reject)

    # When / Then: the public command receives one stable rank-runtime blocker.
    with pytest.raises(RankTrainingRuntimeError, match="physical chain drift"):
        run_default_rank_ridge_training(tmp_path, protocol.protocol_id)


def _mock_parent_reads(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    model: RidgeExperimentArtifact,
    diagnostic: ModelDiagnosticReport,
    backtest: PortfolioBacktestReport,
) -> None:
    for path in (
        root / "model_diagnostics" / DIAGNOSTIC_ID / "report.json",
        root / "portfolio_backtests" / BACKTEST_ID / "report.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        RidgeArtifactStore,
        "descriptor",
        lambda _store, _model_id: ModelArtifact(
            MODEL_ID,
            "ridge_run_parent",
            DATASET_ID,
            str(root / "model.json"),
            "2" * 64,
        ),
    )
    monkeypatch.setattr(RidgeArtifactStore, "read", lambda _store, _descriptor: model)
    monkeypatch.setattr(ModelDiagnosticStore, "read", lambda _store, _descriptor: diagnostic)
    monkeypatch.setattr(PortfolioBacktestReportStore, "read", lambda _store, _descriptor: backtest)
