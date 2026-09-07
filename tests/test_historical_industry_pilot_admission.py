from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ashare_lab.data.historical_industry_admission_models import (
    HistoricalIndustryAdmissionError,
)
from ashare_lab.data.historical_industry_calendar import (
    HistoricalIndustryCalendarEvidence,
    HistoricalIndustryCalendarRow,
    build_historical_industry_calendar,
)
from ashare_lab.data.historical_industry_pilot_admission import (
    admit_historical_industry_resolution,
)
from ashare_lab.data.historical_industry_resolution import (
    HistoricalIndustryResolutionInputs,
    resolve_historical_industry_pilot,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionReport,
)
from ashare_lab.data.schema_registry import SchemaRegistry
from tests.test_historical_industry_resolution import _inputs

ROOT = Path(__file__).parents[1]


def test_resolution_admission_separates_source_eligibility_and_unknown_interval() -> None:
    # Given: the four-branch resolution fixture and one exact calendar per source date.
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
    calendars = tuple(_calendar(row.source.provider_publication_date) for row in resolution.rows)
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v2.json")

    # When: the complete resolution crosses the unified source-only admission gate.
    batch = admit_historical_industry_resolution(
        resolution,
        registry,
        calendars=calendars,
        admitted_at=datetime(2026, 7, 27, 20, tzinfo=UTC),
    )

    # Then: pre-listing knowledge waits for eligibility while CAPCO retains UNKNOWN_UNTIL.
    prospectus = batch.admissions[1].pit_candidate
    capco_candidate = batch.admissions[3].pit_candidate
    assert prospectus.source_available_at < prospectus.eligible_from
    assert prospectus.usable_from == prospectus.eligible_from
    assert prospectus.unknown_from is None
    assert capco_candidate.source_available_at > capco_candidate.eligible_from
    assert capco_candidate.unknown_until == capco_candidate.source_available_at
    assert batch.unknown_interval_count == 1
    assert batch.research_use_authorized is False


def test_resolution_admission_rejects_missing_date_only_calendar() -> None:
    # Given: a resolved date-only source with no exact calendar evidence.
    resolution = _resolution()
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v2.json")

    # When / Then: admission cannot infer the next open from a calendar convention.
    with pytest.raises(HistoricalIndustryAdmissionError, match="lacks exact calendar"):
        admit_historical_industry_resolution(
            resolution,
            registry,
            calendars=(),
            admitted_at=datetime(2026, 7, 27, 20, tzinfo=UTC),
        )


def test_resolution_admission_rejects_conflicting_calendar_for_same_date() -> None:
    # Given: two materially different calendar artifacts for one publication date.
    resolution = _resolution()
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v2.json")
    publication_date = resolution.rows[0].source.provider_publication_date
    first = _calendar(publication_date)
    second = first.model_copy(update={"rows_sha256": "f" * 64})

    # When / Then: caller order cannot choose which availability evidence wins.
    with pytest.raises(HistoricalIndustryAdmissionError, match="conflicting calendar"):
        admit_historical_industry_resolution(
            resolution,
            registry,
            calendars=(first, second),
            admitted_at=datetime(2026, 7, 27, 20, tzinfo=UTC),
        )


def _resolution() -> HistoricalIndustryResolutionReport:
    base, supplemental, consistency, sse, capco = _inputs()
    return resolve_historical_industry_pilot(
        HistoricalIndustryResolutionInputs(
            base,
            supplemental,
            (consistency,),
            (sse,),
            (capco,),
        ),
        resolved_at=datetime(2026, 7, 27, 19, tzinfo=UTC),
    )


def _calendar(publication_date: date) -> HistoricalIndustryCalendarEvidence:
    rows = tuple(
        HistoricalIndustryCalendarRow(
            cal_date=(publication_date + timedelta(days=offset)).strftime("%Y%m%d"),
            exchange="SSE",
            is_open=offset == 2,
            quality_status="ACCEPTED",
            schema_manifest_id=f"schema_{'a' * 64}",
            source_snapshot_id=f"snap_{offset:064x}",
            source_row_sha256=f"{offset:064x}",
        )
        for offset in range(3)
    )
    return build_historical_industry_calendar(rows, publication_date=publication_date)
