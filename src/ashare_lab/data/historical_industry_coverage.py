"""Deterministic completeness gate for source-only historical industries."""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from ashare_lab.data.historical_industry_coverage_models import (
    HistoricalIndustryCoverageDecision,
    HistoricalIndustryCoverageError,
    HistoricalIndustryCoverageReport,
    HistoricalIndustryUnknownInterval,
)
from ashare_lab.data.historical_industry_pilot_models import (
    PilotIndustryAdmission,
    PilotIndustryAdmissionBatch,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionReport,
    HistoricalIndustryResolutionRow,
)
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection

_REPORT_VERSION: Final = "historical_industry_coverage_v1"


@dataclass(frozen=True, slots=True)
class HistoricalIndustryCoverageEvaluation:
    """Exact research window and observation time for one coverage decision."""

    coverage_start: datetime
    coverage_end_exclusive: datetime
    evaluated_at: datetime


def evaluate_historical_industry_coverage(
    selection: StratifiedCandidateSelection,
    resolution: HistoricalIndustryResolutionReport,
    batch: PilotIndustryAdmissionBatch,
    evaluation: HistoricalIndustryCoverageEvaluation,
) -> HistoricalIndustryCoverageReport:
    """Evaluate exact population, source consistency, and PIT interval coverage."""
    _validate_scope(selection, resolution, batch, evaluation)
    selected = {item.symbol for item in selection.selected}
    resolution_by_symbol = {item.symbol: item for item in resolution.rows}
    admissions_by_symbol: dict[str, list[PilotIndustryAdmission]] = defaultdict(list)
    for admission in batch.admissions:
        admissions_by_symbol[admission.pit_candidate.symbol].append(admission)
    admitted_symbols = set(admissions_by_symbol)
    missing = tuple(sorted(selected - admitted_symbols))
    unexpected = tuple(sorted(admitted_symbols - selected))
    duplicates = tuple(
        sorted(symbol for symbol, items in admissions_by_symbol.items() if len(items) > 1)
    )
    conflicts = _conflicting_symbols(admissions_by_symbol)
    lineage_mismatches = _lineage_mismatches(
        selected,
        resolution_by_symbol,
        admissions_by_symbol,
    )
    exactly_admitted = selected - set(missing) - set(duplicates) - set(lineage_mismatches)
    unknown_intervals = _overlapping_unknown_intervals(
        tuple(item for item in batch.admissions if item.pit_candidate.symbol in exactly_admitted),
        evaluation.coverage_start,
        evaluation.coverage_end_exclusive,
    )
    missing_population = selection.candidate_count - len(exactly_admitted)
    reasons: list[str] = []
    if missing:
        reasons.append("SELECTED_SOURCE_COVERAGE_INCOMPLETE")
    if unexpected:
        reasons.append("UNEXPECTED_ADMISSION_SYMBOL")
    if duplicates:
        reasons.append("DUPLICATE_ADMISSION_SYMBOL")
    if conflicts:
        reasons.append("CONFLICTING_ADMISSION_VALUE")
    if lineage_mismatches:
        reasons.append("SOURCE_LINEAGE_MISMATCH")
    if missing_population > 0:
        reasons.append("TARGET_POPULATION_NOT_ADMITTED")
    if unknown_intervals:
        reasons.append("UNKNOWN_INTERVAL_OVERLAPS_RESEARCH_WINDOW")
    blockers = tuple(reasons)
    decision = (
        HistoricalIndustryCoverageDecision.BLOCKED
        if blockers
        else HistoricalIndustryCoverageDecision.READY_FOR_RESEARCH_ADMISSION_REVIEW
    )
    draft = HistoricalIndustryCoverageReport(
        report_id=f"historical_industry_coverage_{'0' * 64}",
        report_version=_REPORT_VERSION,
        evaluated_at=evaluation.evaluated_at,
        selection_id=selection.selection_id,
        resolution_id=resolution.resolution_id,
        admission_batch_id=batch.batch_id,
        candidate_universe_sha256=selection.candidate_universe_sha256,
        coverage_start=evaluation.coverage_start,
        coverage_end_exclusive=evaluation.coverage_end_exclusive,
        population_count=selection.candidate_count,
        selected_count=len(selected),
        admitted_selected_count=len(exactly_admitted),
        population_missing_count=missing_population,
        missing_selected_symbols=missing,
        unexpected_admission_symbols=unexpected,
        duplicate_admission_symbols=duplicates,
        conflicting_admission_symbols=conflicts,
        lineage_mismatch_symbols=lineage_mismatches,
        unknown_intervals=unknown_intervals,
        blocking_reasons=blockers,
        decision=decision,
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"report_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"report_id": f"historical_industry_coverage_{digest}"})


def _validate_scope(
    selection: StratifiedCandidateSelection,
    resolution: HistoricalIndustryResolutionReport,
    batch: PilotIndustryAdmissionBatch,
    evaluation: HistoricalIndustryCoverageEvaluation,
) -> None:
    identities_match = (
        resolution.selection_id == selection.selection_id
        and batch.resolution_id == resolution.resolution_id
    )
    if not identities_match:
        detail = "parent identities differ"
        raise HistoricalIndustryCoverageError(detail)
    selected_symbols = tuple(item.symbol for item in selection.selected)
    valid_scope = (
        len(set(selected_symbols)) == selection.sample_size
        and len(selected_symbols) == selection.sample_size
        and selection.sample_size <= selection.candidate_count
    )
    if not valid_scope:
        detail = "selection population contract differs"
        raise HistoricalIndustryCoverageError(detail)
    clocks = (
        evaluation.coverage_start,
        evaluation.coverage_end_exclusive,
        evaluation.evaluated_at,
    )
    if any(clock.utcoffset() is None for clock in clocks):
        detail = "coverage clocks must be timezone-aware"
        raise HistoricalIndustryCoverageError(detail)
    if evaluation.coverage_start >= evaluation.coverage_end_exclusive:
        detail = "coverage interval is empty or reversed"
        raise HistoricalIndustryCoverageError(detail)


def _conflicting_symbols(
    admissions_by_symbol: dict[str, list[PilotIndustryAdmission]],
) -> tuple[str, ...]:
    conflicting: list[str] = []
    for symbol, admissions in admissions_by_symbol.items():
        values = {
            (
                item.pit_candidate.taxonomy,
                item.pit_candidate.industry_code,
                item.pit_candidate.industry_name,
                item.pit_candidate.usable_from,
            )
            for item in admissions
        }
        if len(values) > 1:
            conflicting.append(symbol)
    return tuple(sorted(conflicting))


def _lineage_mismatches(
    selected: set[str],
    resolution_by_symbol: dict[str, HistoricalIndustryResolutionRow],
    admissions_by_symbol: dict[str, list[PilotIndustryAdmission]],
) -> tuple[str, ...]:
    mismatches: list[str] = []
    for symbol in sorted(selected & set(admissions_by_symbol)):
        resolved = resolution_by_symbol.get(symbol)
        admissions = admissions_by_symbol[symbol]
        if resolved is None or any(
            item.raw.source.observation_id != resolved.source.observation_id for item in admissions
        ):
            mismatches.append(symbol)
    return tuple(mismatches)


def _overlapping_unknown_intervals(
    admissions: tuple[PilotIndustryAdmission, ...],
    coverage_start: datetime,
    coverage_end_exclusive: datetime,
) -> tuple[HistoricalIndustryUnknownInterval, ...]:
    intervals: list[HistoricalIndustryUnknownInterval] = []
    for admission in admissions:
        candidate = admission.pit_candidate
        if (
            candidate.unknown_from is not None
            and candidate.unknown_until is not None
            and candidate.eligible_from < coverage_end_exclusive
            and coverage_start < candidate.unknown_until
        ):
            intervals.append(
                HistoricalIndustryUnknownInterval(
                    symbol=candidate.symbol,
                    unknown_from=candidate.eligible_from,
                    unknown_until=candidate.unknown_until,
                )
            )
    return tuple(sorted(intervals, key=lambda item: item.symbol))


__all__ = (
    "HistoricalIndustryCoverageDecision",
    "HistoricalIndustryCoverageError",
    "HistoricalIndustryCoverageEvaluation",
    "HistoricalIndustryCoverageReport",
    "evaluate_historical_industry_coverage",
)
