from datetime import date, timedelta
from pathlib import Path

import pytest

from ashare_lab.data.historical_industry_artifacts import (
    write_historical_industry_calendar,
)
from ashare_lab.data.historical_industry_calendar import (
    HistoricalIndustryCalendarError,
    HistoricalIndustryCalendarRow,
    build_historical_industry_calendar,
)


def test_calendar_evidence_proves_every_day_until_first_later_open() -> None:
    # Given: accepted SSE calendar rows spanning publication through the next open.
    rows = _rows()

    # When: the availability calendar is frozen.
    calendar = build_historical_industry_calendar(rows, publication_date=date(2024, 2, 8))

    # Then: all closed days and the first later open are content-addressed evidence.
    assert calendar.start_date == date(2024, 2, 8)
    assert calendar.end_date == date(2024, 2, 19)
    assert calendar.next_open_date == date(2024, 2, 19)
    assert len(calendar.rows) == 12
    assert calendar.calendar_artifact_id.startswith("historical_industry_calendar_")


def test_calendar_evidence_rejects_gap_inside_closed_period() -> None:
    # Given: a calendar that omits one holiday date before the claimed next open.
    rows = tuple(row for row in _rows() if row.cal_date != "20240212")

    # When / Then: absence of a daily fact prevents next-open projection.
    with pytest.raises(HistoricalIndustryCalendarError, match="continuous"):
        build_historical_industry_calendar(rows, publication_date=date(2024, 2, 8))


def test_calendar_evidence_folds_byte_identical_physical_duplicates() -> None:
    # Given: one byte-identical Mongo replay of an exact canonical row.
    rows = (*_rows(), _rows()[1])

    # When: storage duplication is folded without selecting between facts.
    calendar = build_historical_industry_calendar(rows, publication_date=date(2024, 2, 8))

    # Then: the evidence still contains one natural-key row per date.
    assert len(calendar.rows) == 12


def test_calendar_evidence_rejects_conflicting_duplicate_natural_key() -> None:
    # Given: two observations for one date with different Raw row identities.
    conflicting = _rows()[1].model_copy(update={"source_row_sha256": "f" * 64})
    rows = (*_rows(), conflicting)

    # When / Then: replay selection cannot be decided by input order.
    with pytest.raises(HistoricalIndustryCalendarError, match="duplicate"):
        build_historical_industry_calendar(rows, publication_date=date(2024, 2, 8))


def test_calendar_evidence_artifact_is_content_addressed(tmp_path: Path) -> None:
    # Given: one qualified continuous calendar artifact.
    calendar = build_historical_industry_calendar(_rows(), publication_date=date(2024, 2, 8))

    # When: the exact evidence is published.
    artifact = write_historical_industry_calendar(calendar, tmp_path)

    # Then: the precomputed calendar identity owns immutable bytes.
    assert artifact.path == tmp_path / calendar.calendar_artifact_id / "manifest.json"


def _rows() -> tuple[HistoricalIndustryCalendarRow, ...]:
    start = date(2024, 2, 8)
    return tuple(
        HistoricalIndustryCalendarRow(
            cal_date=(start + timedelta(days=offset)).strftime("%Y%m%d"),
            exchange="SSE",
            is_open=1 if offset in {0, 11} else 0,
            quality_status="ACCEPTED",
            schema_manifest_id=f"schema_{'a' * 64}",
            source_snapshot_id=f"snap_{offset:064x}",
            source_row_sha256=f"{offset:064x}",
        )
        for offset in range(12)
    )
