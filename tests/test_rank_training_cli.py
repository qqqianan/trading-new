from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab import rank_training_cli
from ashare_lab.ml.contracts import ModelArtifact
from ashare_lab.ml.registry import (
    DatasetSnapshotId,
    ModelId,
    ModelRecord,
    ModelStatus,
    TrainingRunId,
)
from ashare_lab.research.model_governance import ApprovalScope, TrainingApproval
from ashare_lab.research.preflight import PreflightRequest, ResearchIdentity
from ashare_lab.research_cli import app
from ashare_lab.services.rank_training_runtime import RankTrainingRuntimeError
from ashare_lab.services.training import GovernedTrainingResult

RUNNER = CliRunner()


def test_rank_training_cli_publishes_draft_without_holdout_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: clean reproducibility evidence and one completed governed rank training.
    protocol_id = "model_protocol_" + "a" * 64
    model_id = "ridge_model_" + "b" * 64

    def approve(_request: PreflightRequest) -> ResearchIdentity:
        return ResearchIdentity("c" * 40, "d" * 64, "1.1.0", "ashare_quant")

    def train(_root: Path, _protocol_id: str) -> GovernedTrainingResult:
        artifact = ModelArtifact(model_id, "ridge_rank_run_test", "ds_abc", "model.json", "e" * 64)
        approval = TrainingApproval(
            approved=True,
            scope=ApprovalScope.DEVELOPMENT_TRAINING,
            rulebook_version="1.1.0",
            checks=(),
        )
        record = ModelRecord(
            ModelId(model_id),
            DatasetSnapshotId("ds_abc"),
            TrainingRunId("ridge_rank_run_test"),
            ModelStatus.DRAFT,
        )
        return GovernedTrainingResult(artifact, approval, record)

    monkeypatch.setattr(rank_training_cli, "run_research_preflight", approve)
    monkeypatch.setattr(rank_training_cli, "run_default_rank_ridge_training", train)

    # When: the owner runs the exact preregistered candidate.
    result = RUNNER.invoke(
        app,
        [
            "train-ridge-rank",
            "--protocol-id",
            protocol_id,
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: the DRAFT identity is shown and final holdout remains explicitly sealed.
    assert result.exit_code == 0
    assert model_id in result.stdout.replace("\n", "")
    assert protocol_id in result.stdout.replace("\n", "")
    assert "final holdout: SEALED" in result.stdout


def test_rank_training_cli_reports_protocol_chain_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: clean code but a rank protocol whose parent chain no longer verifies.
    def approve(_request: PreflightRequest) -> ResearchIdentity:
        return ResearchIdentity("c" * 40, "d" * 64, "1.1.0", "ashare_quant")

    def reject(_root: Path, _protocol_id: str) -> GovernedTrainingResult:
        detail = "parent chain differs"
        raise RankTrainingRuntimeError(detail)

    monkeypatch.setattr(rank_training_cli, "run_research_preflight", approve)
    monkeypatch.setattr(rank_training_cli, "run_default_rank_ridge_training", reject)

    # When: the rejected protocol is requested through the real CLI surface.
    result = RUNNER.invoke(
        app,
        [
            "train-ridge-rank",
            "--protocol-id",
            "model_protocol_" + "a" * 64,
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: the command fails closed without presenting a model identity.
    assert result.exit_code == 2
    assert "BLOCKED" in result.stdout
    assert "parent chain differs" in result.stdout
