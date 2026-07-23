from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab.research.model_attribution.store import ModelAttributionDescriptor
from ashare_lab.research.preflight import PreflightRequest
from ashare_lab.research_cli import app


def test_model_attribute_cli_discloses_non_tuning_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: clean preflight and one completed immutable attribution descriptor.
    descriptor = ModelAttributionDescriptor(
        report_id="model_attribution_" + "b" * 64,
        report_path=tmp_path / "report.json",
        data_sha256="b" * 64,
    )

    def clean_preflight(_request: PreflightRequest) -> str:
        return "clean"

    def publish_attribution(_root: Path, _diagnostic_id: str) -> ModelAttributionDescriptor:
        return descriptor

    monkeypatch.setattr(
        "ashare_lab.model_attribution_cli.run_research_preflight",
        clean_preflight,
    )
    monkeypatch.setattr(
        "ashare_lab.model_attribution_cli.run_model_performance_attribution",
        publish_attribution,
    )

    # When: the operator requests attribution from one exact parent diagnosis.
    result = CliRunner().invoke(
        app,
        [
            "model-attribute",
            "--diagnostic-report-id",
            "model_diagnostic_" + "a" * 64,
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: the CLI publishes identity and keeps tuning and holdout sealed.
    assert result.exit_code == 0
    assert descriptor.report_id in result.stdout.replace("\n", "")
    assert "tuning: FORBIDDEN" in result.stdout
    assert "final holdout: SEALED" in result.stdout
