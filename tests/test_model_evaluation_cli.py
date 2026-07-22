from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab import model_evaluation_cli
from ashare_lab.research.experiments.promotion import evaluate_model_promotion
from ashare_lab.research.experiments.promotion_store import PromotionEvaluationDescriptor
from ashare_lab.research.experiments.protocol_identity import create_rank_aligned_protocol
from ashare_lab.research.preflight import PreflightRequest, ResearchIdentity
from ashare_lab.research_cli import app
from ashare_lab.services.model_promotion_runtime import (
    ModelPromotionRuntimeError,
    ModelPromotionRuntimeResult,
)

from .test_model_promotion import DIAGNOSTIC_ID, passing_diagnostic
from .test_model_protocol import protocol_request

RUNNER = CliRunner()


def test_model_evaluate_cli_publishes_decision_without_holdout_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: clean preflight and one immutable development gate evaluation.
    protocol = create_rank_aligned_protocol(protocol_request())
    evaluation = evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())
    evaluation_id = "model_promotion_" + "a" * 64

    def approve(_request: PreflightRequest) -> ResearchIdentity:
        return ResearchIdentity("b" * 40, "c" * 64, "1.1.0", "ashare_quant")

    def evaluate(
        _root: Path,
        _protocol_id: str,
        _model_id: str,
        _diagnostic_id: str,
    ) -> ModelPromotionRuntimeResult:
        descriptor = PromotionEvaluationDescriptor(
            evaluation_id=evaluation_id,
            report_path=tmp_path / "report.json",
            data_sha256="a" * 64,
        )
        return ModelPromotionRuntimeResult(descriptor, evaluation)

    monkeypatch.setattr(model_evaluation_cli, "run_research_preflight", approve, raising=False)
    monkeypatch.setattr(
        model_evaluation_cli,
        "run_default_model_promotion_evaluation",
        evaluate,
        raising=False,
    )

    # When: the operator evaluates the exact frozen candidate chain.
    result = RUNNER.invoke(
        app,
        [
            "model-evaluate",
            "--protocol-id",
            protocol.protocol_id,
            "--model-id",
            evaluation.model_id,
            "--diagnostic-report-id",
            DIAGNOSTIC_ID,
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: the content identity and decision are shown while final data stays sealed.
    assert result.exit_code == 0
    assert evaluation_id in result.stdout.replace("\n", "")
    assert evaluation.decision.value in result.stdout
    assert "final holdout: SEALED" in result.stdout


def test_model_evaluate_cli_maps_runtime_failure_to_blocked_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: clean preflight followed by a lineage mismatch at the formal runtime boundary.
    def approve(_request: PreflightRequest) -> ResearchIdentity:
        return ResearchIdentity("b" * 40, "c" * 64, "1.1.0", "ashare_quant")

    def block(
        _root: Path,
        _protocol_id: str,
        _model_id: str,
        _diagnostic_id: str,
    ) -> ModelPromotionRuntimeResult:
        detail = "lineage differs"
        raise ModelPromotionRuntimeError(detail)

    monkeypatch.setattr(model_evaluation_cli, "run_research_preflight", approve)
    monkeypatch.setattr(model_evaluation_cli, "run_default_model_promotion_evaluation", block)

    # When: the operator evaluates a mismatched candidate chain.
    result = RUNNER.invoke(
        app,
        [
            "model-evaluate",
            "--protocol-id",
            "model_protocol_" + "a" * 64,
            "--model-id",
            "ridge_model_" + "b" * 64,
            "--diagnostic-report-id",
            "model_diagnostic_" + "c" * 64,
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: no success-shaped output is emitted for failed governance evidence.
    assert result.exit_code == 2
    assert "BLOCKED: model_promotion_runtime: lineage differs" in result.stdout
