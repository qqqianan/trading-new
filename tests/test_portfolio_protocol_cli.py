from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab.research.experiments.portfolio_protocol_store import (
    PortfolioProtocolDescriptor,
)
from ashare_lab.research.preflight import PreflightRequest
from ashare_lab.research_cli import app


def test_portfolio_preregister_cli_keeps_candidate_unimplemented(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: clean preflight and one completed immutable protocol descriptor.
    descriptor = PortfolioProtocolDescriptor(
        protocol_id="portfolio_protocol_" + "b" * 64,
        manifest_path=tmp_path / "manifest.json",
        data_sha256="b" * 64,
    )

    def clean_preflight(_request: PreflightRequest) -> str:
        return "clean"

    def preregister(
        _root: Path,
        _attribution_id: str,
        _registered_at: datetime,
        _registered_by: str,
    ) -> PortfolioProtocolDescriptor:
        return descriptor

    monkeypatch.setattr(
        "ashare_lab.portfolio_protocol_cli.run_research_preflight",
        clean_preflight,
    )
    monkeypatch.setattr(
        "ashare_lab.portfolio_protocol_cli.run_factor_anchor_veto_preregistration",
        preregister,
    )

    # When: the owner freezes the portfolio experiment from one exact attribution.
    result = CliRunner().invoke(
        app,
        [
            "portfolio-preregister",
            "--attribution-report-id",
            "model_attribution_" + "a" * 64,
            "--registered-at",
            "2026-07-23T20:00:00+08:00",
            "--project-root",
            str(tmp_path),
        ],
    )

    # Then: the CLI discloses no target construction and no holdout authority.
    assert result.exit_code == 0
    assert descriptor.protocol_id in result.stdout.replace("\n", "")
    assert "candidate: NOT_IMPLEMENTED" in result.stdout
    assert "final holdout: FORBIDDEN" in result.stdout
