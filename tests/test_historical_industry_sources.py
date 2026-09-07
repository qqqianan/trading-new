from datetime import UTC, date, datetime

from ashare_lab.data.historical_industry_source_models import HistoricalIndustrySourceKind
from ashare_lab.data.historical_industry_sources import (
    source_from_capco,
    source_from_cninfo,
    source_from_cninfo_prospectus,
    source_from_sse,
)
from ashare_lab.data.sse_industry_bridge import audit_sse_prospectus_candidate
from tests.test_cninfo_industry_bridge import _found_bridge_report
from tests.test_historical_industry_admission import _report as capco_report
from tests.test_historical_industry_resolution import _missing, _supplement
from tests.test_sse_industry_bridge import Provider, _candidate


def test_cninfo_source_adapter_preserves_exact_date_only_document() -> None:
    # Given: one FOUND original listing-document audit.
    report = _found_bridge_report()

    # When: it crosses the unified source boundary.
    source = source_from_cninfo(report)

    # Then: identity, provider clock, taxonomy, and PDF remain exact inputs.
    assert report.evidence is not None
    assert source.source_kind is HistoricalIndustrySourceKind.CNINFO_LISTING
    assert source.source_audit_id == report.audit_id
    assert source.symbol == "301149.SZ"
    assert source.timestamp_precision == report.evidence.timestamp_precision.value
    assert source.document_sha256 == report.evidence.pdf_sha256
    assert source.research_use_authorized is False


def test_sse_source_adapter_uses_disclosure_date_not_recorded_at_as_date_only() -> None:
    # Given: one hash-linked independent SSE confirmation.
    report = audit_sse_prospectus_candidate(
        Provider(),
        _candidate(),
        audited_at=datetime(2026, 7, 27, 14, tzinfo=UTC),
        text_extractor=lambda _content: "公司属于 C31 黑色金属冶炼和压延加工业",
    )

    # When: it crosses the unified source boundary.
    source = source_from_sse(report)

    # Then: the date-only SSEDATE owns projection, not provider_recorded_at.
    assert source.source_kind is HistoricalIndustrySourceKind.SSE_PROSPECTUS
    assert source.provider_publication_date.isoformat() == "2021-11-22"
    assert source.timestamp_precision == "DATE_ONLY"
    assert source.parent_audit_ids == (report.candidate.parent_consistency_id,)


def test_prospectus_source_adapter_retains_failed_base_parent() -> None:
    # Given: one deterministic supplemental prospectus linked to a base miss.
    parent = _missing("001230.SZ", date(2022, 7, 15), "a", "missing")
    report = _supplement(parent, "c")

    # When: it crosses the unified source boundary.
    source = source_from_cninfo_prospectus(report)

    # Then: supplemental attribution cannot be relabeled as an original listing hit.
    assert source.source_kind is HistoricalIndustrySourceKind.CNINFO_PROSPECTUS
    assert source.parent_audit_ids == (parent.audit_id,)
    assert source.source_audit_id == report.audit_id


def test_capco_source_adapter_retains_post_listing_unknown_start() -> None:
    # Given: the later CAPCO company classification.
    report = capco_report()

    # When: it crosses the unified source boundary.
    source = source_from_capco(report)

    # Then: unlike pre-listing documents, it retains an explicit unknown interval.
    assert source.source_kind is HistoricalIndustrySourceKind.CAPCO_MEMBERSHIP
    assert source.unknown_from == report.candidate.listing_date
    assert source.provider_publication_date == report.candidate.publication_date
    assert source.source_page_number == 1
