"""Raw, quality, lineage, and PIT components for unified pilot admission."""

import hashlib
from datetime import datetime
from typing import Final

from ashare_lab.data.historical_industry_admission_models import (
    HistoricalIndustryQualityStatus,
)
from ashare_lab.data.historical_industry_pilot_models import (
    PilotIndustryLineage,
    PilotIndustryPitCandidate,
    PilotIndustryQualityReport,
    PilotIndustryRawObservation,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionRow,
)

_TRANSFORM_VERSION: Final = "2.0.0"


def build_pilot_raw(
    row: HistoricalIndustryResolutionRow,
    resolution_id: str,
    schema_manifest_id: str,
) -> PilotIndustryRawObservation:
    """Bind the selected source observation to resolution and schema identities."""
    identity = f"{resolution_id}|{row.source.observation_id}|{schema_manifest_id}"
    return PilotIndustryRawObservation(
        raw_id=f"historical_industry_pilot_raw_{hashlib.sha256(identity.encode()).hexdigest()}",
        schema_manifest_id=schema_manifest_id,
        resolution_id=resolution_id,
        source=row.source,
    )


def build_pilot_quality(raw: PilotIndustryRawObservation) -> PilotIndustryQualityReport:
    """Record the fixed source-only checks for one resolved Raw row."""
    checks = (
        "fixed_resolution_row",
        "official_source_found",
        "document_hash_present",
        "security_and_listing_identity_match",
        "taxonomy_code_name_present",
        "research_authority_disabled",
    )
    digest = hashlib.sha256(f"{raw.raw_id}|{'|'.join(checks)}".encode()).hexdigest()
    return PilotIndustryQualityReport(
        quality_report_id=f"historical_industry_pilot_quality_{digest}",
        raw_id=raw.raw_id,
        status=HistoricalIndustryQualityStatus.QUALIFIED_SOURCE_ONLY,
        checks=checks,
    )


def build_pilot_lineage(
    row: HistoricalIndustryResolutionRow,
    raw: PilotIndustryRawObservation,
    resolution_id: str,
    calendar_id: str | None,
) -> PilotIndustryLineage:
    """Trace every candidate field to source, lifecycle, resolution, or calendar."""
    upstream = (
        resolution_id,
        row.source.source_audit_id,
        *row.universe_event_ids,
        *((calendar_id,) if calendar_id is not None else ()),
    )
    mappings = tuple(
        f"pit_candidate.{field}<-{source}"
        for field, source in (
            ("symbol", f"{row.source.observation_id}.symbol"),
            ("listing_date", f"{resolution_id}.rows.listing_date"),
            ("source_kind", f"{row.source.observation_id}.source_kind"),
            ("taxonomy", f"{row.source.observation_id}.taxonomy"),
            ("industry_code", f"{row.source.observation_id}.industry_code"),
            ("industry_name", f"{row.source.observation_id}.industry_name"),
            ("eligible_from", f"{resolution_id}.rows.listing_date"),
            ("source_available_at", _availability_mapping(row, calendar_id)),
            ("usable_from", "max(source_available_at,eligible_from)"),
            ("unknown_from", f"{row.source.observation_id}.unknown_from"),
        )
    )
    digest = hashlib.sha256(f"{raw.raw_id}|{'|'.join(upstream)}".encode()).hexdigest()
    return PilotIndustryLineage(
        lineage_edge_id=f"lineage_{digest}",
        upstream_artifact_ids=upstream,
        calendar_artifact_id=calendar_id,
        transform_version=_TRANSFORM_VERSION,
        field_mappings=mappings,
    )


def build_pilot_candidate(
    row: HistoricalIndustryResolutionRow,
    quality: PilotIndustryQualityReport,
    source_available_at: datetime,
    eligible_from: datetime,
    usable_from: datetime,
) -> PilotIndustryPitCandidate:
    """Create a source-only PIT candidate with separate usability clocks."""
    source = row.source
    identity = f"{source.observation_id}|{quality.quality_report_id}|{usable_from.isoformat()}"
    return PilotIndustryPitCandidate(
        candidate_id=(
            f"historical_industry_pilot_candidate_{hashlib.sha256(identity.encode()).hexdigest()}"
        ),
        symbol=source.symbol,
        listing_date=source.listing_date,
        source_kind=source.source_kind.value,
        taxonomy=source.taxonomy,
        industry_code=source.industry_code,
        industry_name=source.industry_name,
        source_available_at=source_available_at,
        eligible_from=eligible_from,
        usable_from=usable_from,
        unknown_from=source.unknown_from,
        unknown_until=source_available_at if source.unknown_from is not None else None,
        quality_status=quality.status,
    )


def _availability_mapping(
    row: HistoricalIndustryResolutionRow,
    calendar_id: str | None,
) -> str:
    if calendar_id is not None:
        return f"{calendar_id}.rows.next_open_date"
    return f"{row.source.observation_id}.provider_published_at"
