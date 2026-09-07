from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab import historical_industry_coverage_cli
from tests.test_historical_industry_coverage import _evidence


def test_coverage_cli_persists_explicit_blocked_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: exact selection, resolution, and admission manifests for a partial population.
    selection, resolution, batch = _evidence(candidate_count=842)
    selection_path = tmp_path / "selection.json"
    resolution_path = tmp_path / "resolution.json"
    batch_path = tmp_path / "batch.json"
    selection_path.write_text(selection.model_dump_json(), encoding="utf-8")
    resolution_path.write_text(resolution.model_dump_json(), encoding="utf-8")
    batch_path.write_text(batch.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(historical_industry_coverage_cli, "_SOURCE_ROOT", tmp_path)

    # When: the operator evaluates the fixed research interval from explicit parents.
    result = CliRunner().invoke(
        historical_industry_coverage_cli.app,
        [
            "--selection",
            str(selection_path),
            "--resolution",
            str(resolution_path),
            "--admission-batch",
            str(batch_path),
            "--coverage-start",
            "2020-01-01T00:00:00+00:00",
            "--coverage-end-exclusive",
            "2025-01-01T00:00:00+00:00",
        ],
    )

    # Then: one immutable BLOCKED report records both population and PIT gaps.
    assert result.exit_code == 0
    assert "decision=BLOCKED" in result.stdout
    assert "population_missing_count=838" in result.stdout
    assert "unknown_interval_count=1" in result.stdout
    assert "research_use_authorized=False" in result.stdout
    assert (
        len(tuple((tmp_path / "historical_industry_coverage_reports").glob("*/manifest.json"))) == 1
    )
