import hashlib
import json
from datetime import UTC, date, datetime

import httpx2
import pytest
from pydantic import ValidationError

from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeCandidate,
    BridgeStatus,
    CninfoIndustryBridgeAudit,
)
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    ProspectusBridgeCandidate,
    audit_cninfo_prospectus_candidate,
)
from ashare_lab.data.sync_service import RequestPacer
from ashare_lab.services.cninfo_prospectus_batch import (
    CninfoProspectusBatchError,
    build_cninfo_prospectus_batch,
    eligible_prospectus_candidates,
)


def test_prospectus_audit_binds_parent_and_exact_official_evidence() -> None:
    # Given: a parent listing-audit failure and one explicit full prospectus.
    security = json.dumps(
        [
            {
                "code": "001230",
                "orgId": "gfbj0839122",
                "zwjc": "劲旅环境",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()
    announcements = _announcement_payload(
        (("1213930269", "首次公开发行股票招股说明书", 1656864000000),)
    )
    pdf = b"%PDF-official-prospectus"

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/information/topSearch/query"):
            return httpx2.Response(200, content=security)
        if request.url.path.endswith("/hisAnnouncement/query"):
            return httpx2.Response(200, content=announcements)
        return httpx2.Response(200, content=pdf)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=lambda _seconds: None))

        # When: the supplemental source audit parses the exact prospectus.
        report = audit_cninfo_prospectus_candidate(
            provider,
            ProspectusBridgeCandidate(
                parent_audit_id=f"cninfo_industry_bridge_audit_{'a' * 64}",
                symbol="001230.SZ",
                listing_date=date(2022, 7, 15),
            ),
            audited_at=datetime(2026, 7, 27, 9, tzinfo=UTC),
            text_extractor=lambda _content: "所属行业\uff1aC38 电气机械和器材制造业",
        )

    # Then: parent linkage, response bytes, PDF, and disclosure remain source-only.
    assert report.status is BridgeStatus.FOUND
    assert report.evidence is not None
    assert report.candidate.parent_audit_id.endswith("a" * 64)
    assert report.evidence.announcement_response_sha256 == hashlib.sha256(announcements).hexdigest()
    assert report.evidence.industry_code == "C38"
    assert report.research_use_authorized is False


def test_prospectus_missing_retains_empty_response_hash() -> None:
    # Given: an exact security identity and an official zero-row prospectus response.
    security = json.dumps(
        [
            {
                "code": "688190",
                "orgId": "gfbj0839122",
                "zwjc": "云路股份",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()
    empty = _announcement_payload(())

    def respond(request: httpx2.Request) -> httpx2.Response:
        content = security if request.url.path.endswith("/information/topSearch/query") else empty
        return httpx2.Response(200, content=content)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=lambda _seconds: None))

        # When: the supplemental audit fails at official-document discovery.
        report = audit_cninfo_prospectus_candidate(
            provider,
            ProspectusBridgeCandidate(
                parent_audit_id=f"cninfo_industry_bridge_audit_{'b' * 64}",
                symbol="688190.SH",
                listing_date=date(2021, 11, 26),
            ),
            audited_at=datetime(2026, 7, 27, 10, tzinfo=UTC),
        )

    # Then: the empty response remains comparable to later non-empty observations.
    assert report.status is BridgeStatus.MISSING
    assert report.trace is not None
    assert report.trace.announcement_response_sha256 == hashlib.sha256(empty).hexdigest()
    assert report.failure_reason == "final_prospectus_missing"


def test_prospectus_identity_failure_retains_security_hash() -> None:
    # Given: an official identity response with no exact security match.
    security = b"[]"

    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=security)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=lambda _seconds: None))

        # When: supplemental discovery cannot establish one organization identity.
        report = audit_cninfo_prospectus_candidate(
            provider,
            ProspectusBridgeCandidate(
                parent_audit_id=f"cninfo_industry_bridge_audit_{'c' * 64}",
                symbol="688190.SH",
                listing_date=date(2021, 11, 26),
            ),
            audited_at=datetime(2026, 7, 27, 11, tzinfo=UTC),
        )

    # Then: the rejected boundary remains content-addressable without an org guess.
    assert report.failure_reason == "security_identity_not_unique"
    assert report.trace is not None
    assert report.trace.security_response_sha256 == hashlib.sha256(security).hexdigest()
    assert report.trace.org_id is None


def test_current_prospectus_audit_rejects_missing_trace() -> None:
    # Given: a current-version missing outcome without its required query evidence.
    candidate = ProspectusBridgeCandidate(
        parent_audit_id=f"cninfo_industry_bridge_audit_{'d' * 64}",
        symbol="688190.SH",
        listing_date=date(2021, 11, 26),
    )

    # When / Then: versioned validation fails closed instead of loading partial evidence.
    with pytest.raises(ValidationError, match="requires source trace"):
        CninfoProspectusBridgeAudit(
            audit_id=f"cninfo_prospectus_bridge_audit_{'e' * 64}",
            audit_version="cninfo_prospectus_bridge_audit_v6",
            audited_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
            candidate=candidate,
            status=BridgeStatus.MISSING,
            failure_reason="final_prospectus_missing",
            evidence=None,
            trace=None,
            research_use_authorized=False,
        )


def test_prospectus_batch_error_has_stable_boundary() -> None:
    # Given: one exact supplemental linkage failure.
    error = CninfoProspectusBatchError("candidate keys differ")

    # When: the operator renders the typed failure.
    rendered = str(error)

    # Then: the boundary and non-secret detail remain stable.
    assert rendered == "cninfo_prospectus_batch: candidate keys differ"


def test_prospectus_batch_rejects_missing_ordered_audit() -> None:
    # Given: one eligible candidate but no matching supplemental outcome.
    candidates = (
        ProspectusBridgeCandidate(
            parent_audit_id=f"cninfo_industry_bridge_audit_{'f' * 64}",
            symbol="001230.SZ",
            listing_date=date(2022, 7, 15),
        ),
    )

    # When / Then: partial batches cannot silently drop failed candidates.
    with pytest.raises(CninfoProspectusBatchError, match="ordered parent set"):
        build_cninfo_prospectus_batch(
            f"cninfo_bridge_batch_audit_{'a' * 64}",
            candidates,
            (),
            audited_at=datetime(2026, 7, 27, 13, tzinfo=UTC),
        )


def test_prospectus_candidates_include_only_explicit_base_missing() -> None:
    # Given: one missing disclosure, one conflicting disclosure, and their parent batch.
    missing = _base_missing("001230.SZ", "explicit_industry_disclosure_missing")
    conflicting = _base_missing("688475.SH", "explicit_industry_disclosure_conflicting")

    # When: supplemental candidates are derived from persisted base outcomes.
    candidates = eligible_prospectus_candidates((missing, conflicting))

    # Then: only the exact missing reason is eligible; conflicts cannot be auto-resolved.
    assert candidates == (
        ProspectusBridgeCandidate(
            parent_audit_id=missing.audit_id,
            symbol="001230.SZ",
            listing_date=date(2022, 7, 15),
        ),
    )


def _announcement_payload(rows: tuple[tuple[str, str, int], ...]) -> bytes:
    announcements = [
        {
            "announcementId": announcement_id,
            "announcementTitle": title,
            "announcementTime": timestamp,
            "adjunctUrl": f"finalpage/2021-11-09/{announcement_id}.PDF",
            "adjunctSize": 1024,
            "adjunctType": "PDF",
            "secCode": "688190",
            "secName": "云路股份",
            "orgId": "gfbj0839122",
        }
        for announcement_id, title, timestamp in rows
    ]
    return json.dumps(
        {
            "totalAnnouncement": len(announcements),
            "announcements": announcements,
            "hasMore": False,
        },
        ensure_ascii=False,
    ).encode()


def _base_missing(symbol: str, reason: str) -> CninfoIndustryBridgeAudit:
    listing_date = date(2022, 7, 15) if symbol == "001230.SZ" else date(2022, 12, 28)
    return CninfoIndustryBridgeAudit(
        audit_id=f"cninfo_industry_bridge_audit_{symbol[:6] * 10}0000",
        audit_version="cninfo_industry_bridge_audit_v4",
        audited_at=datetime(2026, 7, 27, tzinfo=UTC),
        candidate=BridgeCandidate(symbol=symbol, listing_date=listing_date),
        status=BridgeStatus.MISSING,
        failure_reason=reason,
        evidence=None,
        research_use_authorized=False,
    )
