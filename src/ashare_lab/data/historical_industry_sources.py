"""Unified source observations from governed historical-industry audits."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ashare_lab.data.capco_membership_models import (
    CapcoMembershipAudit,
    CapcoMembershipStatus,
)
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeStatus,
    CninfoBridgeEvidence,
    CninfoIndustryBridgeAudit,
)
from ashare_lab.data.cninfo_prospectus_bridge import CninfoProspectusBridgeAudit
from ashare_lab.data.historical_industry_source_models import (
    HistoricalIndustrySourceError,
    HistoricalIndustrySourceKind,
    HistoricalIndustrySourceObservation,
)
from ashare_lab.data.sse_industry_models import SseProspectusIndustryAudit

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class _SourceFields:
    kind: HistoricalIndustrySourceKind
    audit_id: str
    parent_ids: tuple[str, ...]
    audited_at: datetime
    symbol: str
    listing_date: date
    published_at: datetime
    precision: str
    document_sha256: str
    page_number: int | None
    security_name: str | None
    taxonomy: str
    industry_code: str
    industry_name: str
    unknown_from: date | None


def source_from_cninfo(
    report: CninfoIndustryBridgeAudit,
) -> HistoricalIndustrySourceObservation:
    """Normalize one FOUND original listing-document audit."""
    evidence = _cninfo_evidence(
        report.status,
        report.evidence,
        research_use_authorized=report.research_use_authorized,
    )
    return _cninfo_source(
        HistoricalIndustrySourceKind.CNINFO_LISTING,
        report.audit_id,
        (),
        report.audited_at,
        evidence,
    )


def source_from_cninfo_prospectus(
    report: CninfoProspectusBridgeAudit,
) -> HistoricalIndustrySourceObservation:
    """Normalize one parent-linked FOUND prospectus supplement."""
    evidence = _cninfo_evidence(
        report.status,
        report.evidence,
        research_use_authorized=report.research_use_authorized,
    )
    return _cninfo_source(
        HistoricalIndustrySourceKind.CNINFO_PROSPECTUS,
        report.audit_id,
        (report.candidate.parent_audit_id,),
        report.audited_at,
        evidence,
    )


def source_from_sse(report: SseProspectusIndustryAudit) -> HistoricalIndustrySourceObservation:
    """Normalize a hash-linked exchange confirmation using its disclosure date."""
    if (
        report.status is not BridgeStatus.FOUND
        or report.evidence is None
        or report.research_use_authorized
    ):
        detail = "SSE audit is not a non-authorized FOUND observation"
        raise HistoricalIndustrySourceError(detail)
    evidence = report.evidence
    valid = (
        evidence.security_code == report.candidate.symbol.split(".", maxsplit=1)[0]
        and evidence.pdf_sha256 == report.candidate.expected_pdf_sha256
    )
    if not valid:
        detail = "SSE audit identity or cross-source PDF hash differs"
        raise HistoricalIndustrySourceError(detail)
    published_at = datetime.combine(evidence.disclosure_date, time(), _SHANGHAI)
    return _source(
        _SourceFields(
            HistoricalIndustrySourceKind.SSE_PROSPECTUS,
            report.audit_id,
            (report.candidate.parent_consistency_id,),
            report.audited_at,
            report.candidate.symbol,
            report.candidate.listing_date,
            published_at,
            "DATE_ONLY",
            evidence.pdf_sha256,
            None,
            evidence.security_name,
            evidence.taxonomy,
            evidence.industry_code,
            evidence.industry_name,
            None,
        )
    )


def source_from_capco(report: CapcoMembershipAudit) -> HistoricalIndustrySourceObservation:
    """Normalize one later CAPCO row while retaining its post-listing unknown start."""
    if (
        report.status is not CapcoMembershipStatus.FOUND
        or report.evidence is None
        or report.research_use_authorized
    ):
        detail = "CAPCO audit is not a non-authorized FOUND observation"
        raise HistoricalIndustrySourceError(detail)
    evidence = report.evidence
    valid = (
        evidence.attachment_sha256 == report.candidate.expected_attachment_sha256
        and evidence.security_code == report.candidate.symbol.split(".", maxsplit=1)[0]
    )
    if not valid:
        detail = "CAPCO audit identity or attachment hash differs"
        raise HistoricalIndustrySourceError(detail)
    published_at = datetime.combine(report.candidate.publication_date, time(), _SHANGHAI)
    unknown_from = report.candidate.listing_date
    return _source(
        _SourceFields(
            HistoricalIndustrySourceKind.CAPCO_MEMBERSHIP,
            report.audit_id,
            (
                report.candidate.parent_archive_audit_id,
                report.candidate.parent_conflict_audit_id,
            ),
            report.audited_at,
            report.candidate.symbol,
            report.candidate.listing_date,
            published_at,
            "DATE_ONLY",
            evidence.attachment_sha256,
            evidence.page_number,
            evidence.security_name,
            f"CAPCO_{report.candidate.year}",
            evidence.industry_code,
            evidence.industry_name,
            unknown_from,
        )
    )


def _cninfo_evidence(
    status: BridgeStatus,
    evidence: CninfoBridgeEvidence | None,
    *,
    research_use_authorized: bool,
) -> CninfoBridgeEvidence:
    if status is not BridgeStatus.FOUND or evidence is None or research_use_authorized:
        detail = "CNInfo audit is not a non-authorized FOUND observation"
        raise HistoricalIndustrySourceError(detail)
    return evidence


def _cninfo_source(
    kind: HistoricalIndustrySourceKind,
    audit_id: str,
    parent_ids: tuple[str, ...],
    audited_at: datetime,
    evidence: CninfoBridgeEvidence,
) -> HistoricalIndustrySourceObservation:
    return _source(
        _SourceFields(
            kind,
            audit_id,
            parent_ids,
            audited_at,
            evidence.symbol,
            evidence.listing_date,
            evidence.provider_announced_at,
            evidence.timestamp_precision.value,
            evidence.pdf_sha256,
            None,
            None,
            evidence.taxonomy,
            evidence.industry_code,
            evidence.industry_name,
            None,
        )
    )


def _source(fields: _SourceFields) -> HistoricalIndustrySourceObservation:
    draft = HistoricalIndustrySourceObservation(
        observation_id=f"historical_industry_source_{'0' * 64}",
        source_kind=fields.kind,
        source_audit_id=fields.audit_id,
        parent_audit_ids=fields.parent_ids,
        audited_at=fields.audited_at,
        symbol=fields.symbol,
        listing_date=fields.listing_date,
        provider_published_at=fields.published_at,
        provider_publication_date=fields.published_at.date(),
        timestamp_precision=fields.precision,
        document_sha256=fields.document_sha256,
        source_page_number=fields.page_number,
        security_name=fields.security_name,
        taxonomy=fields.taxonomy,
        industry_code=fields.industry_code,
        industry_name=fields.industry_name,
        unknown_from=fields.unknown_from,
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"observation_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return draft.model_copy(
        update={
            "observation_id": f"historical_industry_source_{hashlib.sha256(payload).hexdigest()}"
        }
    )
