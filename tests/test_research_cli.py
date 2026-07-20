from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab import research_cli
from ashare_lab.research.factors.report_store import FactorReportDescriptor
from ashare_lab.research.preflight import (
    PreflightRequest,
    PreflightRule,
    ResearchIdentity,
    ResearchPreflightError,
)
from ashare_lab.research_cli import app

RUNNER = CliRunner()
ROOT = Path(__file__).parents[1]


def test_research_cli_dry_run_writes_plan_without_training(tmp_path: Path) -> None:
    # Given: the real governed repository and an isolated report directory.
    output = tmp_path / "reports"

    # When: the operator executes the one-click command in dry-run mode.
    result = RUNNER.invoke(
        app,
        ["dry-run", "--project-root", str(ROOT), "--output-dir", str(output)],
    )

    # Then: a development-only plan is written without model or holdout access.
    assert result.exit_code == 0
    assert "final holdout: SEALED" in result.stdout
    assert "training: NOT_EXECUTED" in result.stdout
    assert tuple(output.glob("research_report_*/report.json"))
    assert tuple(output.glob("research_report_*/report.zh-CN.md"))


def test_research_cli_returns_nonzero_for_invalid_project_root(tmp_path: Path) -> None:
    # Given: a directory without Git or dependency identity.
    output = tmp_path / "reports"

    # When: preflight runs through the CLI boundary.
    result = RUNNER.invoke(
        app,
        ["dry-run", "--project-root", str(tmp_path), "--output-dir", str(output)],
    )

    # Then: the stable preflight reason is visible and no report is claimed complete.
    assert result.exit_code != 0
    assert "git_identity" in result.stdout
    assert not output.exists()


def test_research_cli_blocks_real_diagnostics_before_runtime_when_worktree_is_dirty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the reproducibility preflight rejects an uncommitted worktree.
    calls = 0

    def reject(_request: PreflightRequest) -> ResearchIdentity:
        raise ResearchPreflightError(PreflightRule.DIRTY_WORKTREE, "uncommitted changes")

    def diagnose_runtime(_project_root: Path) -> FactorReportDescriptor:
        nonlocal calls
        calls += 1
        message = "diagnostic runtime must not execute"
        raise AssertionError(message)

    monkeypatch.setattr(research_cli, "run_research_preflight", reject)
    monkeypatch.setattr(research_cli, "run_default_factor_diagnostics", diagnose_runtime)

    # When: the real diagnostic command is requested.
    result = RUNNER.invoke(app, ["diagnose", "--project-root", str(tmp_path)])

    # Then: it returns a stable blocker before reading feature or label artifacts.
    assert result.exit_code == 2
    assert "dirty_worktree" in result.stdout
    assert calls == 0
