from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab import historical_industry_admission_cli
from tests.test_historical_industry_admission import _calendar, _report


def test_admission_cli_writes_calendar_and_source_only_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one exact CAPCO manifest and governed calendar evidence.
    source_path = tmp_path / "capco.json"
    source_path.write_text(_report().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        historical_industry_admission_cli,
        "load_historical_industry_calendar",
        lambda _root, _publication: _calendar(),
    )
    output_root = tmp_path / "output"

    # When: the operator runs the source-only admission chain.
    result = CliRunner().invoke(
        historical_industry_admission_cli.app,
        [
            "--capco-membership",
            str(source_path),
            "--output-root",
            str(output_root),
        ],
    )

    # Then: both immutable artifacts exist and research authority remains disabled.
    assert result.exit_code == 0
    assert "available_at=2024-02-19T09:30:00+08:00" in result.stdout
    assert "research_use_authorized=False" in result.stdout
    calendars = tuple((output_root / "historical_industry_calendars").glob("*/manifest.json"))
    admissions = tuple((output_root / "historical_industry_admissions").glob("*/manifest.json"))
    assert len(calendars) == 1
    assert len(admissions) == 1


def test_admission_cli_does_not_relabel_admitted_at_as_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an audit admitted years after its provider publication.
    report = _report().model_copy(update={"audited_at": datetime(2026, 7, 27, tzinfo=UTC)})
    source_path = tmp_path / "capco.json"
    source_path.write_text(report.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        historical_industry_admission_cli,
        "load_historical_industry_calendar",
        lambda _root, _publication: _calendar(),
    )

    # When: the admission command executes.
    result = CliRunner().invoke(
        historical_industry_admission_cli.app,
        ["--capco-membership", str(source_path), "--output-root", str(tmp_path / "out")],
    )

    # Then: provider date plus calendar, not ingestion time, owns availability.
    assert result.exit_code == 0
    assert "available_at=2024-02-19T09:30:00+08:00" in result.stdout
