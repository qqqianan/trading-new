"""Source-only admission gate for official historical industry evidence."""

import hashlib
import json
from datetime import datetime
from typing import Final

from ashare_lab.data.capco_membership_models import (
    CapcoMembershipAudit,
    CapcoMembershipEvidence,
    CapcoMembershipStatus,
)
from ashare_lab.data.historical_industry_admission_models import (
    HistoricalIndustryAdmission,
    HistoricalIndustryAdmissionError,
    HistoricalIndustryQualityReport,
    HistoricalIndustryQualityStatus,
    HistoricalIndustryRawObservation,
)
from ashare_lab.data.historical_industry_calendar import HistoricalIndustryCalendarEvidence
from ashare_lab.data.historical_industry_projection import (
    TRANSFORM_VERSION,
    build_admission_lineage,
    build_pit_candidate,
    project_next_open,
)
from ashare_lab.data.schema_registry import SchemaRegistry

_ADMISSION_VERSION: Final = "historical_industry_admission_v2"
_EXPECTED_FIELDS: Final = (
    "symbol",
    "security_name",
    "taxonomy",
    "industry_code",
    "industry_name",
    "unknown_from",
    "provider_publication_date",
    "source_page_number",
)


def admit_capco_membership(
    report: CapcoMembershipAudit,
    registry: SchemaRegistry,
    *,
    calendar: HistoricalIndustryCalendarEvidence,
    admitted_at: datetime,
) -> HistoricalIndustryAdmission:
    """Build Raw, quality, lineage, and PIT evidence without research authority."""
    _accepted_evidence(report)
    endpoint = registry.endpoint("capco_membership")
    if endpoint.field_names != _EXPECTED_FIELDS:
        detail = "historical industry schema fields do not match admission contract"
        raise HistoricalIndustryAdmissionError(detail)
    projection = project_next_open(
        report.temporal_resolution.provider_publication_date,
        calendar,
    )
    raw = _raw_observation(report, registry.manifest_id)
    quality = _quality_report(raw)
    lineage = build_admission_lineage(
        raw,
        report,
        calendar.calendar_artifact_id,
        projection.calendar_dates_sha256,
    )
    pit_candidate = build_pit_candidate(raw, quality, lineage, projection.available_at)
    draft = HistoricalIndustryAdmission(
        admission_id=f"historical_industry_admission_{'0' * 64}",
        admission_version=_ADMISSION_VERSION,
        admitted_at=admitted_at,
        raw=raw,
        quality=quality,
        lineage=lineage,
        pit_candidate=pit_candidate,
        research_use_authorized=False,
    )
    identity = _digest(draft)
    return draft.model_copy(update={"admission_id": f"historical_industry_admission_{identity}"})


def _accepted_evidence(report: CapcoMembershipAudit) -> CapcoMembershipEvidence:
    match report.status:
        case CapcoMembershipStatus.FOUND:
            evidence = report.evidence
        case CapcoMembershipStatus.MISSING:
            detail = "CAPCO source audit is not FOUND"
            raise HistoricalIndustryAdmissionError(detail)
    valid = (
        evidence is not None
        and not report.research_use_authorized
        and evidence.attachment_sha256 == report.candidate.expected_attachment_sha256
        and evidence.security_code == report.candidate.symbol.split(".", maxsplit=1)[0]
        and report.temporal_resolution.unknown_from == report.candidate.listing_date
        and report.temporal_resolution.provider_publication_date
        == report.candidate.publication_date
        and report.temporal_resolution.availability_status == "PENDING_NEXT_TRADING_SESSION_OPEN"
    )
    if not valid or evidence is None:
        detail = "CAPCO source audit linkage or temporal evidence is invalid"
        raise HistoricalIndustryAdmissionError(detail)
    return evidence


def _raw_observation(
    report: CapcoMembershipAudit,
    schema_manifest_id: str,
) -> HistoricalIndustryRawObservation:
    evidence = _accepted_evidence(report)
    identity = f"{report.audit_id}|{schema_manifest_id}|{TRANSFORM_VERSION}"
    return HistoricalIndustryRawObservation(
        raw_id=f"historical_industry_raw_{hashlib.sha256(identity.encode()).hexdigest()}",
        schema_manifest_id=schema_manifest_id,
        parent_source_audit_id=report.audit_id,
        parent_archive_audit_id=report.candidate.parent_archive_audit_id,
        parent_conflict_audit_id=report.candidate.parent_conflict_audit_id,
        observed_at=report.audited_at,
        source_document_sha256=evidence.attachment_sha256,
        source_page_number=evidence.page_number,
        symbol=report.candidate.symbol,
        security_name=evidence.security_name,
        taxonomy=f"CAPCO_{report.candidate.year}",
        industry_code=evidence.industry_code,
        industry_name=evidence.industry_name,
        unknown_from=report.temporal_resolution.unknown_from,
        provider_publication_date=report.temporal_resolution.provider_publication_date,
    )


def _quality_report(raw: HistoricalIndustryRawObservation) -> HistoricalIndustryQualityReport:
    checks = (
        "source_audit_found",
        "parent_attachment_sha256_matches",
        "security_identity_matches",
        "industry_code_and_name_present",
        "unknown_interval_precedes_publication",
        "research_authority_disabled",
    )
    if raw.provider_publication_date <= raw.unknown_from:
        detail = "provider publication must follow the unknown interval start"
        raise HistoricalIndustryAdmissionError(detail)
    digest = hashlib.sha256(f"{raw.raw_id}|{'|'.join(checks)}".encode()).hexdigest()
    return HistoricalIndustryQualityReport(
        quality_report_id=f"historical_industry_quality_{digest}",
        raw_id=raw.raw_id,
        status=HistoricalIndustryQualityStatus.QUALIFIED_SOURCE_ONLY,
        checks=checks,
    )


def _digest(admission: HistoricalIndustryAdmission) -> str:
    payload = admission.model_dump(mode="json", exclude={"admission_id"})
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()
