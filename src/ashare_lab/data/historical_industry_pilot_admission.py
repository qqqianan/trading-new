"""Unified source-only admission for a resolved historical-industry pilot."""

import hashlib
import json
from datetime import datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from ashare_lab.data.historical_industry_admission_models import HistoricalIndustryAdmissionError
from ashare_lab.data.historical_industry_calendar import HistoricalIndustryCalendarEvidence
from ashare_lab.data.historical_industry_pilot_components import (
    build_pilot_candidate,
    build_pilot_lineage,
    build_pilot_quality,
    build_pilot_raw,
)
from ashare_lab.data.historical_industry_pilot_models import (
    PilotIndustryAdmission,
    PilotIndustryAdmissionBatch,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionReport,
    HistoricalIndustryResolutionRow,
)
from ashare_lab.data.schema_registry import SchemaRegistry

_BATCH_VERSION: Final = "historical_industry_admission_batch_v1"
_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_EXPECTED_FIELDS: Final = (
    "symbol",
    "listing_date",
    "source_kind",
    "source_observation_id",
    "taxonomy",
    "industry_code",
    "industry_name",
    "provider_publication_date",
    "unknown_from",
)


def admit_historical_industry_resolution(
    resolution: HistoricalIndustryResolutionReport,
    registry: SchemaRegistry,
    *,
    calendars: tuple[HistoricalIndustryCalendarEvidence, ...],
    admitted_at: datetime,
) -> PilotIndustryAdmissionBatch:
    """Admit every resolved row or fail without a partial batch."""
    endpoint = registry.endpoint("resolved_membership")
    if endpoint.field_names != _EXPECTED_FIELDS:
        detail = "resolved historical industry schema differs from admission contract"
        raise HistoricalIndustryAdmissionError(detail)
    calendars_by_date = _calendar_index(calendars)
    admissions = tuple(
        _admit_row(row, resolution.resolution_id, registry.manifest_id, calendars_by_date)
        for row in resolution.rows
    )
    draft = PilotIndustryAdmissionBatch(
        batch_id=f"historical_industry_admission_batch_{'0' * 64}",
        batch_version=_BATCH_VERSION,
        resolution_id=resolution.resolution_id,
        schema_manifest_id=registry.manifest_id,
        admitted_at=admitted_at,
        admissions=admissions,
        resolved_count=len(admissions),
        unknown_interval_count=sum(
            item.pit_candidate.unknown_from is not None for item in admissions
        ),
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"batch_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"batch_id": f"historical_industry_admission_batch_{digest}"})


def _admit_row(
    row: HistoricalIndustryResolutionRow,
    resolution_id: str,
    schema_manifest_id: str,
    calendars: dict[str, HistoricalIndustryCalendarEvidence],
) -> PilotIndustryAdmission:
    source = row.source
    calendar = calendars.get(source.provider_publication_date.isoformat())
    if source.timestamp_precision == "DATE_ONLY":
        if calendar is None:
            detail = f"date-only source lacks exact calendar: {source.symbol}"
            raise HistoricalIndustryAdmissionError(detail)
        source_available_at = datetime.combine(
            calendar.next_open_date,
            time(9, 30),
            _SHANGHAI,
        )
        calendar_id = calendar.calendar_artifact_id
    else:
        source_available_at = source.provider_published_at
        calendar_id = None
    eligible_from = datetime.combine(source.listing_date, time(9, 30), _SHANGHAI)
    usable_from = max(source_available_at, eligible_from)
    raw = build_pilot_raw(row, resolution_id, schema_manifest_id)
    quality = build_pilot_quality(raw)
    lineage = build_pilot_lineage(row, raw, resolution_id, calendar_id)
    candidate = build_pilot_candidate(
        row,
        quality,
        source_available_at,
        eligible_from,
        usable_from,
    )
    draft = PilotIndustryAdmission(
        admission_id=f"historical_industry_pilot_admission_{'0' * 64}",
        raw=raw,
        quality=quality,
        lineage=lineage,
        pit_candidate=candidate,
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"admission_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(
        update={"admission_id": f"historical_industry_pilot_admission_{digest}"}
    )


def _calendar_index(
    calendars: tuple[HistoricalIndustryCalendarEvidence, ...],
) -> dict[str, HistoricalIndustryCalendarEvidence]:
    pairs = tuple((item.start_date.isoformat(), item) for item in calendars)
    grouped: dict[str, HistoricalIndustryCalendarEvidence] = {}
    for key, item in pairs:
        previous = grouped.get(key)
        if previous is not None and previous != item:
            detail = f"conflicting calendar evidence for {key}"
            raise HistoricalIndustryAdmissionError(detail)
        grouped[key] = item
    return grouped
