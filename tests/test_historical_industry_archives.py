from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from typer.testing import CliRunner

from ashare_lab.data import historical_industry_cli
from ashare_lab.data.cli import app
from ashare_lab.data.historical_industry_archives import (
    ArchiveCoverageStatus,
    audit_csrc_archive,
)
from ashare_lab.data.historical_industry_artifacts import write_archive_audit

LIST_URL = "https://www.csrc.gov.cn/csrc/c100103/common_list.shtml"
PAGE_URL = "https://www.csrc.gov.cn/csrc/c100103/c1447170/content.shtml"
PDF_URL = "https://www.csrc.gov.cn/csrc/c100103/c1447170/files/archive.pdf"


def _client(responses: dict[str, tuple[str, bytes]]) -> httpx2.Client:
    def respond(request: httpx2.Request) -> httpx2.Response:
        content_type, content = responses[str(request.url)]
        return httpx2.Response(200, headers={"content-type": content_type}, content=content)

    return httpx2.Client(transport=httpx2.MockTransport(respond), follow_redirects=True)


def test_archive_audit_requires_page_date_and_pdf_evidence() -> None:
    # Given: one official list item whose content page has a publication date and PDF.
    list_html = f'<a href="{PAGE_URL}">2020年4季度上市公司行业分类结果</a>'.encode()
    page_html = (
        '<meta name="ArticleTitle" content="2020年4季度上市公司行业分类结果">'
        '<meta name="description" content="2020年4季度上市公司行业分类结果,2021-01-25">'
        '<meta name="Description" content="">'
        '<a href="files/archive.pdf">附件</a>'
    ).encode()
    responses = {
        LIST_URL: ("text/html", list_html),
        PAGE_URL: ("text/html", page_html),
        PDF_URL: ("application/pdf", b"%PDF-archive"),
    }

    # When: the fixed 2020Q1-2020Q4 coverage is audited.
    with _client(responses) as client:
        report = audit_csrc_archive(
            client,
            start_year=2020,
            end_year=2020,
            audited_at=datetime(2026, 7, 23, 10, tzinfo=UTC),
        )

    # Then: only the quarter with complete source evidence is covered.
    statuses = {(cell.year, cell.quarter): cell.status for cell in report.coverage}
    assert statuses[(2020, 4)] is ArchiveCoverageStatus.FOUND
    assert sum(status is ArchiveCoverageStatus.MISSING for status in statuses.values()) == 3
    assert report.evidence[0].publication_date.isoformat() == "2021-01-25"
    assert report.evidence[0].attachment_url == PDF_URL
    assert len(report.evidence[0].attachment_sha256) == 64


def test_archive_audit_does_not_count_title_without_attachment() -> None:
    # Given: an official list item whose content page has no downloadable PDF.
    list_html = f'<a href="{PAGE_URL}">2020年4季度上市公司行业分类结果</a>'.encode()
    page_html = (
        '<meta name="ArticleTitle" content="2020年4季度上市公司行业分类结果">'
        '<meta name="description" content="2020年4季度上市公司行业分类结果,2021-01-25">'
    ).encode()
    responses = {
        LIST_URL: ("text/html", list_html),
        PAGE_URL: ("text/html", page_html),
    }

    # When: source evidence is audited.
    with _client(responses) as client:
        report = audit_csrc_archive(
            client,
            start_year=2020,
            end_year=2020,
            audited_at=datetime(2026, 7, 23, 10, tzinfo=UTC),
        )

    # Then: missing attachment evidence fails closed.
    quarter_four = next(cell for cell in report.coverage if cell.quarter == 4)
    assert quarter_four.status is ArchiveCoverageStatus.MISSING
    assert quarter_four.reason == "content_page_missing_pdf"
    assert report.evidence == ()


def test_archive_audit_artifact_is_immutable_and_content_addressed(tmp_path: Path) -> None:
    # Given: a completed fail-closed source audit.
    responses = {LIST_URL: ("text/html", b"<html></html>")}
    with _client(responses) as client:
        report = audit_csrc_archive(
            client,
            start_year=2020,
            end_year=2020,
            audited_at=datetime(2026, 7, 23, 10, tzinfo=UTC),
        )

    # When: the report is published twice to the audit artifact directory.
    first = write_archive_audit(report, tmp_path)
    second = write_archive_audit(report, tmp_path)

    # Then: one exact immutable manifest is reused under its audit identity.
    assert first == second
    assert first.path.name == "manifest.json"
    assert first.path.parent.name == report.audit_id
    assert first.path.read_text(encoding="utf-8").endswith("\n")


def test_archive_audit_cli_writes_report_without_database_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the operator CLI and a wire-level official archive response.
    responses = {LIST_URL: ("text/html", b"<html></html>")}

    def client_factory() -> httpx2.Client:
        return _client(responses)

    monkeypatch.setattr(historical_industry_cli, "create_provider_client", client_factory)

    # When: the read-only audit command is invoked through the real Typer surface.
    result = CliRunner().invoke(
        app,
        [
            "audit-industry-archives",
            "--start-year",
            "2020",
            "--end-year",
            "2020",
            "--output-dir",
            str(tmp_path),
        ],
    )

    # Then: a blocked coverage report is written without needing MongoDB.
    assert result.exit_code == 0
    assert "found=0 missing=4 research_use_authorized=False" in result.stdout
    assert len(tuple(tmp_path.glob("industry_archive_audit_*/manifest.json"))) == 1
