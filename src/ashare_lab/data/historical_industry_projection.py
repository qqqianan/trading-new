"""Governed calendar and lineage projection for historical industry candidates."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.historical_industry_admission_models import (
    HistoricalIndustryAdmissionError,
    HistoricalIndustryLineage,
    HistoricalIndustryPitCandidate,
    HistoricalIndustryQualityReport,
    HistoricalIndustryRawObservation,
)
from ashare_lab.data.historical_industry_calendar import HistoricalIndustryCalendarEvidence

TRANSFORM_NAME: Final = "capco_source_audit_to_pit_candidate"
TRANSFORM_VERSION: Final = "1.1.0"
_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_OPEN_TIME: Final = time(9, 30)


@dataclass(frozen=True, slots=True)
class ProjectedAvailability:
    """Next governed session open and the exact input-calendar digest."""

    available_at: datetime
    calendar_dates_sha256: str


def project_next_open(
    publication_date: date,
    calendar: HistoricalIndustryCalendarEvidence,
) -> ProjectedAvailability:
    """Project a date-only publication strictly to the following session open."""
    if calendar.start_date != publication_date:
        detail = "calendar start does not match provider publication date"
        raise HistoricalIndustryAdmissionError(detail)
    return ProjectedAvailability(
        available_at=datetime.combine(calendar.next_open_date, _OPEN_TIME, _SHANGHAI),
        calendar_dates_sha256=calendar.rows_sha256,
    )


def build_admission_lineage(
    raw: HistoricalIndustryRawObservation,
    report: CapcoMembershipAudit,
    calendar_artifact_id: str,
    calendar_dates_sha256: str,
) -> HistoricalIndustryLineage:
    """Trace every candidate field to the exact source audit or calendar."""
    mappings = tuple(
        f"pit_candidate.{field}<-{upstream}.{source}"
        for field, upstream, source in (
            ("symbol", report.audit_id, "candidate.symbol"),
            ("security_name", report.audit_id, "evidence.security_name"),
            ("taxonomy", report.audit_id, "candidate.year"),
            ("industry_code", report.audit_id, "evidence.industry_code"),
            ("industry_name", report.audit_id, "evidence.industry_name"),
            ("unknown_from", report.audit_id, "temporal_resolution.unknown_from"),
            (
                "provider_publication_date",
                report.audit_id,
                "temporal_resolution.provider_publication_date",
            ),
            ("available_at", calendar_artifact_id, "rows.next_open_date"),
        )
    )
    upstream = (report.audit_id, calendar_artifact_id)
    digest = hashlib.sha256(
        (f"{raw.raw_id}|{'|'.join(upstream)}|{calendar_dates_sha256}|{TRANSFORM_VERSION}").encode()
    ).hexdigest()
    return HistoricalIndustryLineage(
        lineage_edge_id=f"lineage_{digest}",
        schema_manifest_id=raw.schema_manifest_id,
        upstream_artifact_ids=upstream,
        calendar_artifact_id=calendar_artifact_id,
        calendar_dates_sha256=calendar_dates_sha256,
        transform_name=TRANSFORM_NAME,
        transform_version=TRANSFORM_VERSION,
        field_mappings=mappings,
    )


def build_pit_candidate(
    raw: HistoricalIndustryRawObservation,
    quality: HistoricalIndustryQualityReport,
    lineage: HistoricalIndustryLineage,
    available_at: datetime,
) -> HistoricalIndustryPitCandidate:
    """Build a source-only candidate without granting research visibility."""
    identity = f"{raw.raw_id}|{quality.quality_report_id}|{lineage.lineage_edge_id}"
    return HistoricalIndustryPitCandidate(
        candidate_id=(
            f"historical_industry_pit_candidate_{hashlib.sha256(identity.encode()).hexdigest()}"
        ),
        source_raw_id=raw.raw_id,
        quality_report_id=quality.quality_report_id,
        lineage_edge_id=lineage.lineage_edge_id,
        symbol=raw.symbol,
        security_name=raw.security_name,
        taxonomy=raw.taxonomy,
        industry_code=raw.industry_code,
        industry_name=raw.industry_name,
        unknown_from=raw.unknown_from,
        provider_publication_date=raw.provider_publication_date,
        available_at=available_at,
        quality_status=quality.status,
    )
