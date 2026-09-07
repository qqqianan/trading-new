from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from typer.testing import CliRunner

from ashare_lab.data import capco_industry_cli
from ashare_lab.data.capco_industry_archives import (
    CAPCO_ARCHIVE_LIST_URL,
    CapcoCoverageStatus,
    audit_capco_archive,
)
from ashare_lab.data.cli import app
from ashare_lab.data.historical_industry_artifacts import write_capco_archive_audit

PAGE_URL = (
    "https://www.capco.org.cn/xhgg/hyfl/hyfljg/202402/20240208/"
    "j_2024020815341400017073777753078836.html"
)
CODE_PDF_URL = "https://sp.capco.org.cn:82/file/2023h1-by-symbol.pdf"
INDUSTRY_PDF_URL = "https://sp.capco.org.cn:82/file/2023h1-by-industry.pdf"


def _client(responses: dict[str, tuple[str, bytes]]) -> httpx2.Client:
    def respond(request: httpx2.Request) -> httpx2.Response:
        content_type, content = responses[str(request.url)]
        return httpx2.Response(200, headers={"content-type": content_type}, content=content)

    return httpx2.Client(transport=httpx2.MockTransport(respond), follow_redirects=True)


def test_capco_audit_selects_code_sorted_pdf_and_publication_date() -> None:
    # Given: one official half-year result with two differently sorted attachments.
    list_html = (f'<a href="{PAGE_URL}">2023年上半年上市公司行业分类结果</a>').encode()
    page_html = (
        "<div>来源\uff1a中国上市公司协会 发布时间\uff1a2024-02-08</div>"
        f'<a href="{INDUSTRY_PDF_URL}">2023年上半年结果\uff08按行业排序\uff09</a>'
        f'<a href="{CODE_PDF_URL}\r\n">2023年上半年结果\uff08按股票代码排序\uff09</a>'
    ).encode()
    responses = {
        CAPCO_ARCHIVE_LIST_URL: ("text/html", list_html),
        PAGE_URL: ("text/html", page_html),
        CODE_PDF_URL: ("application/pdf", b"%PDF-code-sorted"),
    }

    # When: the expected 2023H1-2024H2 interval is audited.
    with _client(responses) as client:
        report = audit_capco_archive(
            client,
            start_year=2023,
            end_year=2024,
            audited_at=datetime(2026, 7, 23, 12, tzinfo=UTC),
        )

    # Then: only complete code-sorted evidence covers the half-year.
    statuses = {(cell.year, cell.half): cell.status for cell in report.coverage}
    assert statuses[(2023, 1)] is CapcoCoverageStatus.FOUND
    assert sum(status is CapcoCoverageStatus.MISSING for status in statuses.values()) == 3
    assert report.evidence[0].publication_date.isoformat() == "2024-02-08"
    assert report.evidence[0].attachment_url == CODE_PDF_URL
    assert report.research_use_authorized is False


def test_capco_audit_fails_closed_without_code_sorted_attachment() -> None:
    # Given: a result page that only exposes the industry-sorted PDF.
    list_html = (f'<a href="{PAGE_URL}">2023年上半年上市公司行业分类结果</a>').encode()
    page_html = (
        "<div>发布时间\uff1a2024-02-08</div>"
        f'<a href="{INDUSTRY_PDF_URL}">2023年上半年结果\uff08按行业排序\uff09</a>'
    ).encode()
    responses = {
        CAPCO_ARCHIVE_LIST_URL: ("text/html", list_html),
        PAGE_URL: ("text/html", page_html),
    }

    # When: the archive is audited.
    with _client(responses) as client:
        report = audit_capco_archive(
            client,
            start_year=2023,
            end_year=2023,
            audited_at=datetime(2026, 7, 23, 12, tzinfo=UTC),
        )

    # Then: a semantically different PDF cannot satisfy the mapping evidence.
    first_half = next(cell for cell in report.coverage if cell.half == 1)
    assert first_half.status is CapcoCoverageStatus.MISSING
    assert first_half.reason == "content_page_missing_code_sorted_pdf"
    assert report.evidence == ()


def test_capco_audit_artifact_is_immutable(tmp_path: Path) -> None:
    # Given: a complete source-only CAPCO audit document.
    responses = {CAPCO_ARCHIVE_LIST_URL: ("text/html", b"<html></html>")}
    with _client(responses) as client:
        report = audit_capco_archive(
            client,
            start_year=2023,
            end_year=2023,
            audited_at=datetime(2026, 7, 23, 12, tzinfo=UTC),
        )

    # When: the exact report is published twice.
    first = write_capco_archive_audit(report, tmp_path)
    second = write_capco_archive_audit(report, tmp_path)

    # Then: both writes resolve to one immutable manifest.
    assert first == second
    assert first.path.parent.name == report.audit_id
    assert first.path.read_text(encoding="utf-8").endswith("\n")


def test_capco_audit_cli_stays_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the real CLI with a wire-level official-list response.
    responses = {CAPCO_ARCHIVE_LIST_URL: ("text/html", b"<html></html>")}

    def client_factory() -> httpx2.Client:
        return _client(responses)

    monkeypatch.setattr(capco_industry_cli, "create_provider_client", client_factory)

    # When: the CAPCO source audit is invoked without MongoDB.
    result = CliRunner().invoke(
        app,
        [
            "audit-capco-industry-archives",
            "--start-year",
            "2023",
            "--end-year",
            "2023",
            "--output-dir",
            str(tmp_path),
        ],
    )

    # Then: a blocked source artifact is produced through the operator surface.
    assert result.exit_code == 0
    assert "found=0 missing=2 research_use_authorized=False" in result.stdout
    assert len(tuple(tmp_path.glob("capco_industry_archive_audit_*/manifest.json"))) == 1
