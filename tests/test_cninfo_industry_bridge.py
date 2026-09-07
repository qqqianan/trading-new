import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx2
import pytest
from typer.testing import CliRunner

from ashare_lab.data import cninfo_industry_cli
from ashare_lab.data.cli import app
from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeCandidate,
    BridgeStatus,
    CninfoIndustryBridgeAudit,
    TimestampPrecision,
    audit_cninfo_candidate,
    classify_provider_timestamp,
)
from ashare_lab.data.cninfo_industry_parser import (
    IndustryDisclosureError,
    IndustryDisclosureFailure,
    parse_industry_disclosure,
    select_listing_announcement,
)
from ashare_lab.data.historical_industry_artifacts import write_cninfo_bridge_audit
from ashare_lab.data.sync_service import RequestPacer


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("所属行业\uff1aC26 化学原料和化学制品制造业", ("C26", "化学原料和化学制品制造业")),
        (
            "所属行业\uff1a根据中国证监会行业指引\uff0c公司属于“C35 专用设备制造业”。",
            ("C35", "专用设备制造业"),
        ),
        ("所属行业\uff1a仪器仪表制造业\uff08C40\uff09", ("C40", "仪器仪表制造业")),
        ("公司所处行业为专用设备制造业\uff08C35\uff09", ("C35", "专用设备制造业")),
        ("发行人所属行业为\u2018F51 批发业\u2019", ("F51", "批发业")),
        ("所属行业为批发业\uff08F51\uff09", ("F51", "批发业")),
    ],
)
def test_industry_disclosure_parses_explicit_listing_statement(
    text: str,
    expected: tuple[str, str],
) -> None:
    # Given: extracted official listing-document text with an explicit industry statement.
    # When: the disclosure is parsed without inferring from business descriptions.
    disclosure = parse_industry_disclosure(text)

    # Then: the exact CSRC code and name are retained.
    assert (disclosure.industry_code, disclosure.industry_name) == expected


def test_industry_disclosure_rejects_conflicting_explicit_codes() -> None:
    # Given: one document containing two incompatible explicit industry declarations.
    text = "所属行业\uff1aC26 化学原料和化学制品制造业。所属行业\uff1aC35 专用设备制造业。"

    # When / Then: ambiguity fails closed instead of selecting a convenient code.
    with pytest.raises(IndustryDisclosureError, match="conflicting") as captured:
        parse_industry_disclosure(text)
    assert captured.value.reason is IndustryDisclosureFailure.CONFLICTING


def test_industry_disclosure_preserves_explicit_csrc_taxonomy_version() -> None:
    # Given: an official statement naming the 2012 CSRC taxonomy inside book-title marks.
    text = (
        "根据中国证监会《上市公司行业分类指引》\uff08 2012 年修订\uff09\uff0c"
        "所属行业\uff1aC35 专用设备制造业"
    )

    # When: the explicit disclosure is parsed.
    disclosure = parse_industry_disclosure(text)

    # Then: the taxonomy version is evidence, not an inferred current classification.
    assert disclosure.taxonomy == "CSRC_2012"


def test_announcement_selection_rejects_cancelled_hint_and_correction() -> None:
    # Given: one final listing announcement mixed with non-authoritative variants.
    payload = _announcement_payload(
        (
            ("1211530798", "首次公开发行股票并在创业板上市之上市公告书\uff08已取消\uff09", 1),
            ("1211530799", "首次公开发行股票并在创业板上市之上市公告书提示性公告", 2),
            ("1211541222", "首次公开发行股票并在创业板上市之上市公告书的更正公告", 3),
            (
                "1211541225",
                "首次公开发行股票并在创业板<em>上市</em>之上市公告书\uff08更新后\uff09",
                4,
            ),
        )
    )

    # When: the official response is parsed and ranked.
    selected = select_listing_announcement(payload)

    # Then: only the final complete announcement can provide source evidence.
    assert selected.announcement_id == "1211541225"
    assert "<em>" not in selected.title


def test_provider_midnight_in_shanghai_is_date_only() -> None:
    # Given: CNInfo's millisecond representation of a publication date without time.
    # When: timestamp precision is classified in the provider's local timezone.
    announced_at, precision = classify_provider_timestamp(1636387200000)

    # Then: midnight is not promoted to a precise intraday availability time.
    assert announced_at.isoformat() == "2021-11-09T00:00:00+08:00"
    assert precision is TimestampPrecision.DATE_ONLY


def test_cninfo_bridge_audit_hashes_query_pdf_and_disclosure() -> None:
    # Given: wire-level security lookup, announcement query, and official PDF responses.
    calls: list[float] = []
    security = json.dumps(
        [
            {
                "code": "301149",
                "orgId": "gfbj0839122",
                "zwjc": "隆华新材",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()
    announcements = _announcement_payload(
        (
            (
                "1211541225",
                "首次公开发行股票并在创业板上市之上市公告书\uff08更新后\uff09",
                1636458067000,
            ),
        )
    )
    pdf = b"%PDF-official-listing-document"

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/information/topSearch/query"):
            return httpx2.Response(200, content=security)
        if request.url.path.endswith("/hisAnnouncement/query"):
            return httpx2.Response(200, content=announcements)
        return httpx2.Response(200, headers={"content-type": "application/pdf"}, content=pdf)

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(
            http,
            RequestPacer(minimum_interval_seconds=0.25, sleeper=calls.append),
        )

        # When: one pre-listing industry bridge candidate is audited.
        report = audit_cninfo_candidate(
            provider,
            BridgeCandidate(symbol="301149.SZ", listing_date=date(2021, 11, 10)),
            audited_at=datetime(2026, 7, 24, 9, tzinfo=UTC),
            text_extractor=lambda _content: "所属行业\uff1aC26 化学原料和化学制品制造业",
        )

    # Then: all three requests and exact evidence remain source-only and content addressed.
    assert report.status is BridgeStatus.FOUND
    assert report.evidence is not None
    assert report.evidence.industry_code == "C26"
    assert report.evidence.pdf_sha256 != report.evidence.announcement_response_sha256
    assert calls == [0.25, 0.25, 0.25]
    assert report.research_use_authorized is False


def test_cninfo_bridge_artifact_is_immutable(tmp_path: Path) -> None:
    # Given: one complete source-only bridge audit.
    root = tmp_path / "bridge"
    report = _found_bridge_report()

    # When: the exact report is published twice.
    first = write_cninfo_bridge_audit(report, root)
    second = write_cninfo_bridge_audit(report, root)

    # Then: one immutable manifest is reused under the audit identity.
    assert first == second
    assert first.path.parent.name == report.audit_id


def test_cninfo_bridge_cli_writes_source_only_failure_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real CLI surface with valid discovery responses and an unreadable PDF.
    root = tmp_path / "bridge-cli"
    security = json.dumps(
        [
            {
                "code": "301149",
                "orgId": "gfbj0839122",
                "zwjc": "隆华新材",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()
    announcements = _announcement_payload(
        (("1211541225", "首次公开发行股票并在创业板上市之上市公告书", 1636458067000),)
    )

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/information/topSearch/query"):
            return httpx2.Response(200, content=security)
        if request.url.path.endswith("/hisAnnouncement/query"):
            return httpx2.Response(200, content=announcements)
        return httpx2.Response(200, content=b"%PDF-unreadable")

    def client_factory() -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(respond))

    def pacer_factory(minimum_interval_seconds: float) -> RequestPacer:
        return RequestPacer(minimum_interval_seconds, sleeper=lambda _seconds: None)

    monkeypatch.setattr(cninfo_industry_cli, "create_provider_client", client_factory)
    monkeypatch.setattr(cninfo_industry_cli, "RequestPacer", pacer_factory)

    # When: one bridge candidate is audited through the operator command.
    result = CliRunner().invoke(
        app,
        [
            "audit-cninfo-industry-bridge",
            "--symbol",
            "301149.SZ",
            "--listing-date",
            "2021-11-10",
            "--output-dir",
            str(root),
        ],
    )

    # Then: extraction failure is durable but cannot authorize research use.
    assert result.exit_code == 0
    assert "status=MISSING research_use_authorized=False" in result.stdout
    assert len(tuple(root.glob("cninfo_industry_bridge_audit_*/manifest.json"))) == 1


def _found_bridge_report() -> CninfoIndustryBridgeAudit:
    calls: list[float] = []
    security = json.dumps(
        [
            {
                "code": "301149",
                "orgId": "gfbj0839122",
                "zwjc": "隆华新材",
                "category": "A股",
                "delisted": "false",
            }
        ],
        ensure_ascii=False,
    ).encode()
    announcements = _announcement_payload(
        (("1211541225", "首次公开发行股票并在创业板上市之上市公告书", 1636458067000),)
    )

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/information/topSearch/query"):
            return httpx2.Response(200, content=security)
        if request.url.path.endswith("/hisAnnouncement/query"):
            return httpx2.Response(200, content=announcements)
        return httpx2.Response(200, content=b"%PDF-official")

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        provider = CninfoArchiveClient(http, RequestPacer(0.1, sleeper=calls.append))
        return audit_cninfo_candidate(
            provider,
            BridgeCandidate(symbol="301149.SZ", listing_date=date(2021, 11, 10)),
            audited_at=datetime(2026, 7, 24, 9, tzinfo=UTC),
            text_extractor=lambda _content: "所属行业\uff1aC26 化学原料和化学制品制造业",
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
            "secCode": "301149",
            "secName": "隆华新材",
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
