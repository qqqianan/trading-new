from datetime import UTC, datetime
from pathlib import Path

import pytest

from ashare_lab.data.historical_industry_coverage import (
    HistoricalIndustryCoverageDecision,
    HistoricalIndustryCoverageError,
    HistoricalIndustryCoverageEvaluation,
    evaluate_historical_industry_coverage,
)
from ashare_lab.data.historical_industry_pilot_admission import (
    admit_historical_industry_resolution,
)
from ashare_lab.data.historical_industry_pilot_models import PilotIndustryAdmissionBatch
from ashare_lab.data.historical_industry_resolution import (
    HistoricalIndustryResolutionInputs,
    resolve_historical_industry_pilot,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionReport,
)
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection
from tests.test_historical_industry_pilot_admission import _calendar
from tests.test_historical_industry_resolution import _inputs

ROOT = Path(__file__).parents[1]


def test_coverage_blocks_partial_population_and_unknown_research_interval() -> None:
    # Given: four admitted pilot rows selected from a governed 842-stock population.
    selection, resolution, batch = _evidence(candidate_count=842)

    # When: coverage is evaluated over the historical research interval.
    report = evaluate_historical_industry_coverage(
        selection,
        resolution,
        batch,
        HistoricalIndustryCoverageEvaluation(
            coverage_start=datetime(2020, 1, 1, tzinfo=UTC),
            coverage_end_exclusive=datetime(2025, 1, 1, tzinfo=UTC),
            evaluated_at=datetime(2026, 7, 27, 21, tzinfo=UTC),
        ),
    )

    # Then: source success cannot hide population gaps or the CAPCO unknown interval.
    assert report.selected_count == 4
    assert report.admitted_selected_count == 4
    assert report.population_count == 842
    assert report.population_missing_count == 838
    assert tuple(item.symbol for item in report.unknown_intervals) == ("688475.SH",)
    assert report.conflicting_admission_symbols == ()
    assert report.decision is HistoricalIndustryCoverageDecision.BLOCKED
    assert report.blocking_reasons == (
        "TARGET_POPULATION_NOT_ADMITTED",
        "UNKNOWN_INTERVAL_OVERLAPS_RESEARCH_WINDOW",
    )
    assert report.research_use_authorized is False


def test_coverage_only_marks_complete_known_population_ready_for_review() -> None:
    # Given: the complete governed population and an interval after all unknowns mature.
    selection, resolution, batch = _evidence(candidate_count=4)

    # When: exact coverage is evaluated without an overlapping unknown interval.
    report = evaluate_historical_industry_coverage(
        selection,
        resolution,
        batch,
        HistoricalIndustryCoverageEvaluation(
            coverage_start=datetime(2024, 2, 20, tzinfo=UTC),
            coverage_end_exclusive=datetime(2025, 1, 1, tzinfo=UTC),
            evaluated_at=datetime(2026, 7, 27, 21, tzinfo=UTC),
        ),
    )

    # Then: the report permits a separate review but never grants research authority.
    assert report.population_missing_count == 0
    assert report.unknown_intervals == ()
    assert report.blocking_reasons == ()
    assert report.decision is HistoricalIndustryCoverageDecision.READY_FOR_RESEARCH_ADMISSION_REVIEW
    assert report.research_use_authorized is False


def test_coverage_rejects_crossed_selection_parent() -> None:
    # Given: otherwise complete evidence whose resolution names another selection.
    selection, resolution, batch = _evidence(candidate_count=4)
    crossed = resolution.model_copy(update={"selection_id": f"cninfo_bridge_selection_{'f' * 64}"})

    # When / Then: explicit artifact inputs cannot be mixed into a coverage report.
    with pytest.raises(HistoricalIndustryCoverageError, match="parent identities differ"):
        evaluate_historical_industry_coverage(
            selection,
            crossed,
            batch,
            HistoricalIndustryCoverageEvaluation(
                coverage_start=datetime(2024, 2, 20, tzinfo=UTC),
                coverage_end_exclusive=datetime(2025, 1, 1, tzinfo=UTC),
                evaluated_at=datetime(2026, 7, 27, 21, tzinfo=UTC),
            ),
        )


def test_coverage_blocks_duplicate_conflicting_admission_values() -> None:
    # Given: one symbol appears twice with materially different industry values.
    selection, resolution, batch = _evidence(candidate_count=4)
    original = batch.admissions[0]
    conflicting_candidate = original.pit_candidate.model_copy(
        update={
            "candidate_id": f"historical_industry_pilot_candidate_{'f' * 64}",
            "industry_code": "C99",
            "industry_name": "冲突分类",
        }
    )
    conflicting_admission = original.model_copy(
        update={
            "admission_id": f"historical_industry_pilot_admission_{'e' * 64}",
            "pit_candidate": conflicting_candidate,
        }
    )
    conflicted_batch = batch.model_copy(
        update={"admissions": (*batch.admissions, conflicting_admission)}
    )

    # When: the conflicting batch crosses the independent coverage gate.
    report = evaluate_historical_industry_coverage(
        selection,
        resolution,
        conflicted_batch,
        HistoricalIndustryCoverageEvaluation(
            coverage_start=datetime(2024, 2, 20, tzinfo=UTC),
            coverage_end_exclusive=datetime(2025, 1, 1, tzinfo=UTC),
            evaluated_at=datetime(2026, 7, 27, 21, tzinfo=UTC),
        ),
    )

    # Then: caller order cannot select a favorable classification.
    assert report.duplicate_admission_symbols == (original.pit_candidate.symbol,)
    assert report.conflicting_admission_symbols == (original.pit_candidate.symbol,)
    assert report.decision is HistoricalIndustryCoverageDecision.BLOCKED
    assert "CONFLICTING_ADMISSION_VALUE" in report.blocking_reasons


def _evidence(
    candidate_count: int,
) -> tuple[
    StratifiedCandidateSelection,
    HistoricalIndustryResolutionReport,
    PilotIndustryAdmissionBatch,
]:
    base, supplemental, consistency, sse, capco = _inputs()
    selection = base.selection.model_copy(update={"candidate_count": candidate_count})
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
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v2.json")
    calendars = tuple(_calendar(row.source.provider_publication_date) for row in resolution.rows)
    batch = admit_historical_industry_resolution(
        resolution,
        registry,
        calendars=calendars,
        admitted_at=datetime(2026, 7, 27, 20, tzinfo=UTC),
    )
    return selection, resolution, batch
