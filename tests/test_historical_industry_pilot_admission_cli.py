from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab import historical_industry_pilot_admission_cli
from ashare_lab.data.historical_industry_resolution import (
    HistoricalIndustryResolutionInputs,
    resolve_historical_industry_pilot,
)
from tests.test_historical_industry_pilot_admission import _calendar
from tests.test_historical_industry_resolution import _inputs


def test_pilot_admission_cli_writes_every_source_only_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one exact four-branch resolution and deterministic calendar adapter.
    base, supplemental, consistency, sse, capco = _inputs()
    resolution = resolve_historical_industry_pilot(
        HistoricalIndustryResolutionInputs(
            base,
            supplemental,
            (consistency,),
            (sse,),
            (capco,),
        ),
        resolved_at=datetime(2026, 7, 27, 19, tzinfo=UTC),
    )
    resolution_path = tmp_path / "resolution.json"
    resolution_path.write_text(resolution.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(historical_industry_pilot_admission_cli, "_SOURCE_ROOT", tmp_path)
    monkeypatch.setattr(
        historical_industry_pilot_admission_cli,
        "load_historical_industry_calendar",
        lambda _root, publication_date: _calendar(publication_date),
    )

    # When: the all-candidate source-only command executes.
    result = CliRunner().invoke(
        historical_industry_pilot_admission_cli.app,
        ["--resolution", str(resolution_path)],
    )

    # Then: calendar, four admissions, and one batch persist without authorization.
    assert result.exit_code == 0
    assert "resolved_count=4" in result.stdout
    assert "unknown_interval_count=1" in result.stdout
    assert "research_use_authorized=False" in result.stdout
    assert (
        len(tuple((tmp_path / "historical_industry_pilot_admissions").glob("*/manifest.json"))) == 4
    )
    assert (
        len(tuple((tmp_path / "historical_industry_admission_batches").glob("*/manifest.json")))
        == 1
    )
