import json
from datetime import UTC, date, datetime

import httpx2
import pytest

from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_bridge import TimestampPrecision
from ashare_lab.data.cninfo_listing_discovery import (
    CninfoDiscoveryStatus,
    CninfoListingDiscoveryAudit,
    CninfoListingDiscoveryEvidence,
    discover_cninfo_listing,
)
from ashare_lab.data.official_bridge_candidates import OfficialBridgeCandidate
from ashare_lab.data.sync_service import RequestPacer
from ashare_lab.services.cninfo_full_discovery import (
    CninfoFullDiscoveryError,
    build_full_discovery_plan,
    build_full_discovery_shard,
    freeze_full_candidate_selection,
)


def test_full_plan_freezes_every_candidate_before_network_work() -> None:
    # Given: an unordered complete candidate population.
    candidates = tuple(reversed(tuple(_candidate(index) for index in range(842))))

    # When: the population is frozen into recoverable discovery shards.
    selection = freeze_full_candidate_selection(candidates)
    plan = build_full_discovery_plan(
        selection,
        shard_size=50,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    )

    # Then: every key occurs once and shard boundaries do not depend on outcomes.
    assert selection.sample_size == selection.candidate_count == 842
    assert tuple(item.symbol for item in selection.selected) == tuple(
        sorted(item.symbol for item in candidates)
    )
    assert len(plan.shards) == 17
    assert (plan.shards[0].start_offset, plan.shards[0].end_offset_exclusive) == (0, 50)
    assert (plan.shards[-1].start_offset, plan.shards[-1].end_offset_exclusive) == (800, 842)
    assert plan.research_use_authorized is False


def test_discovery_records_selected_pdf_without_downloading_it() -> None:
    # Given: exact identity and announcement responses with no PDF response route.
    security = json.dumps(
        [
            {
                "code": "000001",
                "orgId": "org-000001",
                "zwjc": "测试公司",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()
    announcement = json.dumps(
        {
            "totalAnnouncement": 1,
            "announcements": [
                {
                    "announcementId": "announcement-1",
                    "announcementTitle": "首次公开发行股票并上市之上市公告书",
                    "announcementTime": 1640995200000,
                    "adjunctUrl": "final.pdf",
                    "adjunctSize": 100,
                    "adjunctType": "PDF",
                    "secCode": "000001",
                    "secName": "测试公司",
                    "orgId": "org-000001",
                }
            ],
            "hasMore": False,
        },
        ensure_ascii=False,
    ).encode()
    requests: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.url.path)
        payload = security if request.url.path.endswith("topSearch/query") else announcement
        return httpx2.Response(200, content=payload)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=lambda _delay: None))

        # When: stage-one discovery evaluates the candidate.
        audit = discover_cninfo_listing(
            provider,
            _candidate(0),
            discovered_at=datetime(2026, 9, 4, tzinfo=UTC),
        )

    # Then: only two discovery requests occur and the final PDF choice is immutable.
    assert audit.status is CninfoDiscoveryStatus.SELECTED
    assert audit.evidence is not None
    assert audit.evidence.announcement_id == "announcement-1"
    assert audit.evidence.pdf_url.endswith("final.pdf")
    assert len(requests) == 2
    assert audit.research_use_authorized is False


def test_discovery_records_announcement_http_failure_with_response_hash() -> None:
    # Given: identity succeeds before the official announcement endpoint returns 502.
    security = json.dumps(
        [
            {
                "code": "000001",
                "orgId": "org-000001",
                "zwjc": "测试公司",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()
    failure_payload = b"upstream unavailable"

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("topSearch/query"):
            return httpx2.Response(200, content=security)
        return httpx2.Response(502, content=failure_payload)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=lambda _delay: None))

        # When: stage-one discovery observes the provider failure.
        audit = discover_cninfo_listing(
            provider,
            _candidate(0),
            discovered_at=datetime(2026, 9, 4, tzinfo=UTC),
        )

    # Then: the failed response is evidence, not a shard-level exception or a source absence.
    assert audit.status is CninfoDiscoveryStatus.MISSING
    assert audit.failure_reason == "provider_http_error"
    assert audit.failure_trace is not None
    assert audit.failure_trace.stage == "ANNOUNCEMENT_LOOKUP"
    assert audit.failure_trace.http_status == 502
    assert audit.failure_trace.security_response_sha256 is not None
    assert audit.failure_trace.response_sha256 is not None


def test_discovery_records_announcement_transport_failure_after_identity() -> None:
    # Given: identity succeeds before the announcement transport disconnects.
    security = json.dumps(
        [
            {
                "code": "000001",
                "orgId": "org-000001",
                "zwjc": "测试公司",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("topSearch/query"):
            return httpx2.Response(200, content=security)
        message = "offline"
        raise httpx2.ConnectError(message, request=request)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=lambda _delay: None))

        # When: discovery observes a transport failure.
        audit = discover_cninfo_listing(
            provider,
            _candidate(0),
            discovered_at=datetime(2026, 9, 4, tzinfo=UTC),
        )

    # Then: the completed identity response remains linked to the transient failure.
    assert audit.failure_reason == "provider_transport_error"
    assert audit.failure_trace is not None
    assert audit.failure_trace.stage == "ANNOUNCEMENT_LOOKUP"
    assert audit.failure_trace.security_response_sha256 is not None
    assert audit.failure_trace.response_sha256 is None


def test_discovery_records_security_transport_failure() -> None:
    # Given: the provider disconnects before returning security identity evidence.
    def respond(request: httpx2.Request) -> httpx2.Response:
        message = "offline"
        raise httpx2.ConnectError(message, request=request)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=lambda _delay: None))

        # When: discovery cannot complete its first provider stage.
        audit = discover_cninfo_listing(
            provider,
            _candidate(0),
            discovered_at=datetime(2026, 9, 4, tzinfo=UTC),
        )

    # Then: the transient source failure is retained without invented response bytes.
    assert audit.failure_reason == "provider_transport_error"
    assert audit.failure_trace is not None
    assert audit.failure_trace.stage == "SECURITY_LOOKUP"
    assert audit.failure_trace.security_response_sha256 is None


def test_shard_report_keeps_missing_discovery_in_exact_plan_position() -> None:
    # Given: one frozen two-candidate shard and ordered selected/missing audits.
    selection = freeze_full_candidate_selection(tuple(_candidate(index) for index in range(842)))
    plan = build_full_discovery_plan(
        selection,
        shard_size=2,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    audits = (
        _discovery(selection.selected[0], CninfoDiscoveryStatus.SELECTED),
        _discovery(selection.selected[1], CninfoDiscoveryStatus.MISSING),
    )

    # When: the exact shard result is assembled.
    report = build_full_discovery_shard(
        plan,
        selection,
        shard_index=0,
        audits=audits,
        completed_at=datetime(2026, 9, 4, 1, tzinfo=UTC),
    )

    # Then: the failure remains counted and cannot trigger replacement.
    assert tuple(item.candidate.symbol for item in report.audits) == tuple(
        item.symbol for item in selection.selected[:2]
    )
    assert report.selected_count == 1
    assert report.missing_count == 1
    assert report.research_use_authorized is False


def test_shard_report_rejects_plan_with_crossed_universe_hash() -> None:
    # Given: a valid 842-stock plan whose universe hash is replaced after planning.
    selection = freeze_full_candidate_selection(tuple(_candidate(index) for index in range(842)))
    plan = build_full_discovery_plan(
        selection,
        shard_size=2,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    ).model_copy(update={"candidate_universe_sha256": "f" * 64})
    audits = tuple(
        _discovery(candidate, CninfoDiscoveryStatus.MISSING) for candidate in selection.selected[:2]
    )

    # When / Then: matching selection IDs cannot conceal a crossed population.
    with pytest.raises(CninfoFullDiscoveryError, match="plan and selection evidence differ"):
        build_full_discovery_shard(
            plan,
            selection,
            shard_index=0,
            audits=audits,
            completed_at=datetime(2026, 9, 4, 1, tzinfo=UTC),
        )


def _candidate(index: int) -> OfficialBridgeCandidate:
    exchange = ("SZ", "SH", "BJ")[index % 3]
    return OfficialBridgeCandidate(
        symbol=f"{index + 1:06d}.{exchange}",
        listing_date=date(2022, (index % 12) + 1, (index % 27) + 1),
        source_event_ids=(f"event-{index}",),
        universe_schema_manifest_id=f"schema_{'a' * 64}",
        event_type="LISTED",
        quality_status="ACCEPTED",
    )


def _discovery(
    candidate: OfficialBridgeCandidate,
    status: CninfoDiscoveryStatus,
) -> CninfoListingDiscoveryAudit:
    reason = None if status is CninfoDiscoveryStatus.SELECTED else "announcement_missing"
    evidence = None
    if status is CninfoDiscoveryStatus.SELECTED:
        evidence = CninfoListingDiscoveryEvidence(
            org_id="org",
            security_response_sha256="a" * 64,
            announcement_response_sha256="b" * 64,
            announcement_id="announcement",
            announcement_title="上市公告书",
            provider_announced_at=datetime(2022, 1, 1, tzinfo=UTC),
            timestamp_precision=TimestampPrecision.DATE_ONLY,
            pdf_url="https://static.cninfo.com.cn/file.pdf",
        )
    return CninfoListingDiscoveryAudit(
        audit_id=f"cninfo_listing_discovery_{candidate.symbol[:6] * 10}0000",
        audit_version="cninfo_listing_discovery_v1",
        discovered_at=datetime(2026, 9, 4, tzinfo=UTC),
        candidate=candidate,
        status=status,
        failure_reason=reason,
        evidence=evidence,
        research_use_authorized=False,
    )
