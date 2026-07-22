from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from ashare_lab import model_protocol_cli
from ashare_lab.research.experiments.protocol_store import ModelProtocolDescriptor
from ashare_lab.research.preflight import PreflightRequest, ResearchIdentity
from ashare_lab.research_cli import app

RUNNER = CliRunner()


def test_model_preregister_cli_freezes_protocol_without_training_or_holdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: clean preflight identity and one completed append-only registration.
    protocol_id = "model_protocol_" + "a" * 64

    def approve(_request: PreflightRequest) -> ResearchIdentity:
        return ResearchIdentity("b" * 40, "c" * 64, "1.1.0", "ashare_quant")

    def preregister(
        _root: Path,
        _diagnostic_id: str,
        _registered_at: datetime,
        _registered_by: str,
    ) -> ModelProtocolDescriptor:
        return ModelProtocolDescriptor(
            protocol_id=protocol_id,
            manifest_path=tmp_path / "manifest.json",
            data_sha256="a" * 64,
        )

    monkeypatch.setattr(model_protocol_cli, "run_research_preflight", approve)
    monkeypatch.setattr(model_protocol_cli, "run_default_model_preregistration", preregister)

    # When: the owner explicitly preregisters the post-hoc-derived experiment.
    result = RUNNER.invoke(
        app,
        [
            "model-preregister",
            "--diagnostic-report-id",
            "model_diagnostic_" + "d" * 64,
            "--registered-at",
            datetime(2026, 7, 20, 19, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: protocol identity is shown while training and final evaluation remain untouched.
    assert result.exit_code == 0
    assert protocol_id in result.stdout.replace("\n", "")
    assert "training: NOT_EXECUTED" in result.stdout
    assert "final holdout: SEALED" in result.stdout


def test_model_preregister_cli_blocks_naive_registration_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a clean preflight identity that must not receive an ambiguous time.
    def approve(_request: PreflightRequest) -> ResearchIdentity:
        return ResearchIdentity("b" * 40, "c" * 64, "1.1.0", "ashare_quant")

    monkeypatch.setattr(model_protocol_cli, "run_research_preflight", approve)

    # When: the owner supplies a timestamp without an offset.
    result = RUNNER.invoke(
        app,
        [
            "model-preregister",
            "--diagnostic-report-id",
            "model_diagnostic_" + "d" * 64,
            "--registered-at",
            "2026-07-20T19:00:00",
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: preregistration is fail-closed before any artifact can be written.
    assert result.exit_code == 2
    assert "timezone-aware" in result.stdout
