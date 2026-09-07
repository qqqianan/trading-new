from datetime import UTC, date, datetime

from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeCandidate,
    BridgeStatus,
    CninfoBridgeEvidence,
    CninfoIndustryBridgeAudit,
    TimestampPrecision,
)
from ashare_lab.data.cninfo_observation_consistency import build_prospectus_consistency_audit
from ashare_lab.data.cninfo_observation_models import CninfoProspectusConsistencyAudit
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    ProspectusBridgeCandidate,
    ProspectusSourceTrace,
)
from ashare_lab.data.historical_industry_resolution import (
    HistoricalIndustryResolutionInputs,
    resolve_historical_industry_pilot,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionError,
)
from ashare_lab.data.historical_industry_source_models import HistoricalIndustrySourceKind
from ashare_lab.data.official_bridge_candidates import (
    OfficialBridgeCandidate,
)
from ashare_lab.data.sse_industry_bridge import (
    candidate_from_cninfo_consistency,
)
from ashare_lab.data.sse_industry_models import (
    SseIndustryEvidence,
    SseProspectusIndustryAudit,
    SseSourceTrace,
)
from ashare_lab.services.cninfo_bridge_batch import (
    CninfoBridgeBatchAudit,
    build_cninfo_bridge_batch,
)
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection
from ashare_lab.services.cninfo_prospectus_batch import (
    CninfoProspectusBatchAudit,
    build_cninfo_prospectus_batch,
)
from tests.cninfo_prospectus_fixtures import prospectus_audit
from tests.test_cninfo_industry_bridge import _found_bridge_report
from tests.test_historical_industry_admission import _report as capco_report


def test_pilot_resolution_selects_four_governed_source_branches() -> None:
    # Given: base success, stable supplement, unstable supplement plus SSE, and CAPCO conflict.
    base, supplemental, consistency, sse, capco = _inputs()

    # When: the fixed pilot source protocol is resolved.
    report = resolve_historical_industry_pilot(
        HistoricalIndustryResolutionInputs(
            base=base,
            supplemental=supplemental,
            consistencies=(consistency,),
            sse_audits=(sse,),
            capco_audits=(capco,),
        ),
        resolved_at=datetime(2026, 7, 27, 19, tzinfo=UTC),
    )

    # Then: each candidate has one source and unstable CNInfo never wins by success alone.
    assert report.resolved_count == 4
    assert tuple(row.source.source_kind for row in report.rows) == (
        HistoricalIndustrySourceKind.CNINFO_LISTING,
        HistoricalIndustrySourceKind.CNINFO_PROSPECTUS,
        HistoricalIndustrySourceKind.SSE_PROSPECTUS,
        HistoricalIndustrySourceKind.CAPCO_MEMBERSHIP,
    )
    assert report.rows[2].selection_reason == "UNSTABLE_CNINFO_REQUIRES_SSE_CONFIRMATION"
    assert report.rows[3].source.unknown_from == date(2022, 12, 28)
    assert report.research_use_authorized is False


def test_resolution_error_has_stable_boundary() -> None:
    # Given: one deterministic source-resolution failure detail.
    error = HistoricalIndustryResolutionError("duplicate source parent key")

    # When / Then: operators receive the owned boundary and stable reason.
    assert str(error) == ("historical_industry_resolution: duplicate source parent key")


def _inputs() -> tuple[
    CninfoBridgeBatchAudit,
    CninfoProspectusBatchAudit,
    CninfoProspectusConsistencyAudit,
    SseProspectusIndustryAudit,
    CapcoMembershipAudit,
]:
    direct = _found_bridge_report()
    supplement_base = _missing("001230.SZ", date(2022, 7, 15), "a", "missing")
    unstable_base = _missing("688190.SH", date(2021, 11, 26), "b", "missing")
    capco = capco_report()
    conflict_base = _missing(
        "688475.SH",
        date(2022, 12, 28),
        capco.candidate.parent_conflict_audit_id.removeprefix("cninfo_industry_bridge_audit_"),
        "conflict",
    )
    selection = StratifiedCandidateSelection(
        selection_id=f"cninfo_bridge_selection_{'1' * 64}",
        selection_version="cninfo_bridge_pilot_v1",
        candidate_universe_sha256="2" * 64,
        candidate_count=4,
        sample_size=4,
        strata=(),
        selected=tuple(
            _official(audit) for audit in (direct, supplement_base, unstable_base, conflict_base)
        ),
    )
    base = build_cninfo_bridge_batch(
        selection,
        (direct, supplement_base, unstable_base, conflict_base),
        audited_at=datetime(2026, 7, 27, tzinfo=UTC),
    )
    stable_supplement = _supplement(supplement_base, "c")
    unstable_supplement = _supplement(unstable_base, "d")
    supplemental = build_cninfo_prospectus_batch(
        base.batch_id,
        (stable_supplement.candidate, unstable_supplement.candidate),
        (stable_supplement, unstable_supplement),
        audited_at=datetime(2026, 7, 27, tzinfo=UTC),
    )
    consistency = build_prospectus_consistency_audit(
        unstable_supplement.candidate,
        (
            prospectus_audit(
                unstable_supplement.candidate,
                observed_at=datetime(2026, 7, 27, 10, tzinfo=UTC),
                found=True,
                marker="d",
            ),
            prospectus_audit(
                unstable_supplement.candidate,
                observed_at=datetime(2026, 7, 27, 11, tzinfo=UTC),
                found=False,
                marker="e",
            ),
        ),
        assessed_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
    )
    sse_candidate = candidate_from_cninfo_consistency(consistency)
    sse_evidence = SseIndustryEvidence(
        query_response_sha256="4" * 64,
        security_code="688190",
        security_name="云路股份",
        title="首次公开发行股票并在科创板上市招股说明书",
        provider_recorded_at=datetime(2021, 11, 21, 15, 30, tzinfo=UTC),
        disclosure_date=date(2021, 11, 22),
        pdf_url="https://example.com/sse.pdf",
        pdf_sha256=sse_candidate.expected_pdf_sha256,
        pdf_bytes=100,
        taxonomy="CSRC_UNVERSIONED",
        industry_code="C31",
        industry_name="黑色金属冶炼和压延加工业",
        matched_disclosure="公司属于 C31 黑色金属冶炼和压延加工业",
    )
    sse = SseProspectusIndustryAudit(
        audit_id=f"sse_prospectus_industry_audit_{'5' * 64}",
        audit_version="sse_prospectus_industry_audit_v2",
        audited_at=datetime(2026, 7, 27, 14, tzinfo=UTC),
        candidate=sse_candidate,
        status=BridgeStatus.FOUND,
        failure_reason=None,
        evidence=sse_evidence,
        trace=SseSourceTrace(
            query_response_sha256=sse_evidence.query_response_sha256,
            title=sse_evidence.title,
            provider_recorded_at=sse_evidence.provider_recorded_at,
            disclosure_date=sse_evidence.disclosure_date,
            pdf_url=sse_evidence.pdf_url,
            pdf_sha256=sse_evidence.pdf_sha256,
            pdf_bytes=sse_evidence.pdf_bytes,
        ),
        research_use_authorized=False,
    )
    return base, supplemental, consistency, sse, capco


def _missing(
    symbol: str,
    listing_date: date,
    marker: str,
    kind: str,
) -> CninfoIndustryBridgeAudit:
    reason = (
        "explicit_industry_disclosure_conflicting"
        if kind == "conflict"
        else "explicit_industry_disclosure_missing"
    )
    digest = marker if len(marker) == 64 else marker * 64
    return CninfoIndustryBridgeAudit(
        audit_id=f"cninfo_industry_bridge_audit_{digest}",
        audit_version="cninfo_industry_bridge_audit_v8",
        audited_at=datetime(2026, 7, 27, tzinfo=UTC),
        candidate=BridgeCandidate(symbol=symbol, listing_date=listing_date),
        status=BridgeStatus.MISSING,
        failure_reason=reason,
        evidence=None,
        research_use_authorized=False,
    )


def _supplement(
    parent: CninfoIndustryBridgeAudit,
    marker: str,
) -> CninfoProspectusBridgeAudit:
    candidate = ProspectusBridgeCandidate(
        parent_audit_id=parent.audit_id,
        symbol=parent.candidate.symbol,
        listing_date=parent.candidate.listing_date,
    )
    evidence = CninfoBridgeEvidence(
        symbol=candidate.symbol,
        listing_date=candidate.listing_date,
        org_id="org",
        security_response_sha256="1" * 64,
        announcement_response_sha256="2" * 64,
        announcement_id="announcement",
        announcement_title="首次公开发行股票招股说明书",
        provider_announced_at=datetime(2021, 11, 22, tzinfo=UTC),
        timestamp_precision=TimestampPrecision.DATE_ONLY,
        pdf_url="https://example.com/document.pdf",
        pdf_sha256=marker * 64,
        pdf_bytes=100,
        taxonomy="CSRC_2012",
        industry_code="C31",
        industry_name="黑色金属冶炼和压延加工业",
        matched_disclosure="所属行业 C31 黑色金属冶炼和压延加工业",
    )
    trace = ProspectusSourceTrace(
        security_response_sha256=evidence.security_response_sha256,
        org_id=evidence.org_id,
        announcement_response_sha256=evidence.announcement_response_sha256,
        announcement_id=evidence.announcement_id,
        announcement_title=evidence.announcement_title,
        provider_announced_at=evidence.provider_announced_at,
        timestamp_precision=evidence.timestamp_precision,
        pdf_url=evidence.pdf_url,
        pdf_sha256=evidence.pdf_sha256,
        pdf_bytes=evidence.pdf_bytes,
    )
    return CninfoProspectusBridgeAudit(
        audit_id=f"cninfo_prospectus_bridge_audit_{marker * 64}",
        audit_version="cninfo_prospectus_bridge_audit_v6",
        audited_at=datetime(2026, 7, 27, tzinfo=UTC),
        candidate=candidate,
        status=BridgeStatus.FOUND,
        failure_reason=None,
        evidence=evidence,
        trace=trace,
        research_use_authorized=False,
    )


def _official(audit: CninfoIndustryBridgeAudit) -> OfficialBridgeCandidate:
    return OfficialBridgeCandidate(
        symbol=audit.candidate.symbol,
        listing_date=audit.candidate.listing_date,
        source_event_ids=(f"event_{audit.candidate.symbol}",),
        universe_schema_manifest_id=f"schema_{'3' * 64}",
        event_type="LISTED",
        quality_status="ACCEPTED",
    )
