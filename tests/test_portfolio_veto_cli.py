from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab.portfolio.research_store import PortfolioTargetDescriptor
from ashare_lab.research.preflight import PreflightRequest
from ashare_lab.research_cli import app


def test_portfolio_veto_cli_discloses_reused_development_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: clean preflight and one protocol-bound target descriptor.
    descriptor = PortfolioTargetDescriptor(
        artifact_id="portfolio_targets_" + "b" * 64,
        artifact_path=tmp_path / "targets.json",
        data_sha256="b" * 64,
    )

    def clean_preflight(_request: PreflightRequest) -> str:
        return "clean"

    def build_targets(_root: Path, _protocol_id: str) -> PortfolioTargetDescriptor:
        return descriptor

    monkeypatch.setattr(
        "ashare_lab.portfolio_veto_cli.run_research_preflight",
        clean_preflight,
    )
    monkeypatch.setattr(
        "ashare_lab.portfolio_veto_cli.run_factor_anchor_veto_targets",
        build_targets,
    )

    # When: the owner builds targets from one exact protocol.
    result = CliRunner().invoke(
        app,
        [
            "portfolio-veto-targets",
            "--protocol-id",
            "portfolio_protocol_" + "a" * 64,
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: the CLI does not mislabel the artifact as fresh or executable orders.
    assert result.exit_code == 0
    assert descriptor.artifact_id in result.stdout.replace("\n", "")
    assert "evidence: REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE" in result.stdout
    assert "orders: NOT_CREATED" in result.stdout
    assert "final holdout: FORBIDDEN" in result.stdout
