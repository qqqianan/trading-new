import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ashare_lab.data.cninfo_industry_bridge import BridgeStatus
from ashare_lab.data.cninfo_observation_consistency import build_prospectus_consistency_audit
from ashare_lab.data.cninfo_prospectus_bridge import ProspectusBridgeCandidate
from ashare_lab.data.historical_industry_artifacts import write_sse_prospectus_industry_audit
from ashare_lab.data.sse_industry_bridge import (
    SseProspectusCandidate,
    SseSourceLinkError,
    audit_sse_prospectus_candidate,
    candidate_from_cninfo_consistency,
)
from ashare_lab.data.sse_models import SseBulletin, SseBulletinLookup, SsePdfDocument

from .cninfo_prospectus_fixtures import prospectus_audit


class Provider:
    """In-memory official adapter preserving exact query and PDF bytes."""

    def __init__(self, *, pdf: bytes = b"%PDF-sse") -> None:
        self.pdf = pdf

    def search_prospectuses(self, _code: str) -> SseBulletinLookup:
        return SseBulletinLookup(payload=b"official-query", hits=(_bulletin(),))

    def fetch_pdf(self, url: str) -> SsePdfDocument:
        return SsePdfDocument(url=f"https://www.sse.com.cn{url}", content=self.pdf)


class EmptyProvider:
    """Official adapter returning a retained zero-row announcement response."""

    def search_prospectuses(self, _code: str) -> SseBulletinLookup:
        return SseBulletinLookup(payload=b"official-empty-query", hits=())

    def fetch_pdf(self, _url: str) -> SsePdfDocument:
        message = "empty selection must not fetch an attachment"
        raise AssertionError(message)


def test_sse_audit_binds_independent_document_and_industry_hashes() -> None:
    # Given: the unresolved CNInfo observation and exact SSE prospectus evidence.
    candidate = _candidate()
    provider = Provider()

    # When: the independent exchange source is audited.
    report = audit_sse_prospectus_candidate(
        provider,
        candidate,
        audited_at=datetime(2026, 7, 27, 14, tzinfo=UTC),
        text_extractor=lambda _content: "公司属于 C31 黑色金属冶炼和压延加工业",
    )

    # Then: the source remains isolated while preserving exact positive evidence.
    assert report.status is BridgeStatus.FOUND
    assert report.evidence is not None
    assert report.evidence.industry_code == "C31"
    assert report.evidence.query_response_sha256 == hashlib.sha256(b"official-query").hexdigest()
    assert report.evidence.pdf_sha256 == hashlib.sha256(b"%PDF-sse").hexdigest()
    assert report.candidate.parent_consistency_id.endswith("a" * 64)
    assert report.research_use_authorized is False


def test_sse_audit_retains_selected_trace_when_attachment_is_not_pdf() -> None:
    # Given: a selected official row whose attachment boundary returns HTML.
    provider = Provider(pdf=b"<html>blocked</html>")

    # When: the independent source audit reaches the attachment boundary.
    report = audit_sse_prospectus_candidate(
        provider,
        _candidate(),
        audited_at=datetime(2026, 7, 27, 15, tzinfo=UTC),
    )

    # Then: the failure is explicit and its downloaded bytes remain hashed.
    assert report.status is BridgeStatus.MISSING
    assert report.failure_reason == "selected_attachment_is_not_pdf"
    assert report.trace.pdf_sha256 == hashlib.sha256(b"<html>blocked</html>").hexdigest()


def test_sse_audit_rejects_pdf_that_differs_from_cninfo_found_observation() -> None:
    # Given: an exchange PDF whose bytes differ from the parent CNInfo success.
    candidate = _candidate().model_copy(update={"expected_pdf_sha256": "e" * 64})

    # When: the independent exchange attachment is audited.
    report = audit_sse_prospectus_candidate(
        Provider(),
        candidate,
        audited_at=datetime(2026, 7, 27, 15, tzinfo=UTC),
    )

    # Then: title similarity cannot replace exact cross-source byte identity.
    assert report.status is BridgeStatus.MISSING
    assert report.failure_reason == "cross_source_pdf_hash_mismatch"


def test_sse_audit_retains_zero_row_query_as_missing_source_evidence() -> None:
    # Given: an exact official query with no selectable prospectus row.
    provider = EmptyProvider()

    # When: the independent source audit processes the empty response.
    report = audit_sse_prospectus_candidate(
        provider,
        _candidate(),
        audited_at=datetime(2026, 7, 27, 15, tzinfo=UTC),
    )

    # Then: absence is explicit and the raw response remains content-addressed.
    assert report.status is BridgeStatus.MISSING
    assert report.failure_reason == "final_prospectus_not_unique"
    assert report.trace.query_response_sha256 == hashlib.sha256(b"official-empty-query").hexdigest()


def test_sse_candidate_is_derived_from_exact_unstable_cninfo_report() -> None:
    # Given: the immutable CNInfo success-versus-empty consistency report.
    cninfo_candidate = _cninfo_candidate()
    parent = build_prospectus_consistency_audit(
        cninfo_candidate,
        (
            prospectus_audit(
                cninfo_candidate,
                observed_at=datetime(2026, 7, 27, 10, tzinfo=UTC),
                found=True,
                marker="a",
            ),
            prospectus_audit(
                cninfo_candidate,
                observed_at=datetime(2026, 7, 27, 11, tzinfo=UTC),
                found=False,
                marker="b",
            ),
        ),
        assessed_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
    )

    # When: the independent-source candidate is assembled.
    candidate = candidate_from_cninfo_consistency(parent)

    # Then: the exact contradiction report becomes immutable parent evidence.
    assert candidate.parent_consistency_id == parent.consistency_id
    assert candidate.symbol == "688190.SH"
    assert candidate.cninfo_announcement_id == "1211660704"
    assert candidate.expected_pdf_sha256 == "d" * 64


def test_sse_candidate_rejects_noncontradictory_cninfo_report() -> None:
    # Given: a CNInfo report with too few but otherwise consistent observations.
    cninfo_candidate = _cninfo_candidate()
    parent = build_prospectus_consistency_audit(
        cninfo_candidate,
        (
            prospectus_audit(
                cninfo_candidate,
                observed_at=datetime(2026, 7, 27, 10, tzinfo=UTC),
                found=True,
                marker="a",
            ),
        ),
        assessed_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
    )

    # When / Then: an independent query cannot be opened without the contradiction.
    with pytest.raises(SseSourceLinkError, match="query contradiction"):
        candidate_from_cninfo_consistency(parent)


def test_sse_audit_is_persisted_under_its_content_identity(tmp_path: Path) -> None:
    # Given: one completed source-only independent audit.
    report = audit_sse_prospectus_candidate(
        Provider(),
        _candidate(),
        audited_at=datetime(2026, 7, 27, 14, tzinfo=UTC),
        text_extractor=lambda _content: "公司属于 C31 黑色金属冶炼和压延加工业",
    )

    # When: the report crosses the immutable artifact boundary.
    artifact = write_sse_prospectus_industry_audit(report, tmp_path)

    # Then: the precomputed audit identity owns the exact manifest path.
    assert artifact.path == tmp_path / report.audit_id / "manifest.json"


def _candidate() -> SseProspectusCandidate:
    return SseProspectusCandidate(
        parent_consistency_id=f"cninfo_prospectus_consistency_audit_{'a' * 64}",
        cninfo_announcement_id="1211660704",
        expected_pdf_sha256=hashlib.sha256(b"%PDF-sse").hexdigest(),
        symbol="688190.SH",
        listing_date=date(2021, 11, 26),
    )


def _cninfo_candidate() -> ProspectusBridgeCandidate:
    return ProspectusBridgeCandidate(
        parent_audit_id=f"cninfo_industry_bridge_audit_{'c' * 64}",
        symbol="688190.SH",
        listing_date=date(2021, 11, 26),
    )


def _bulletin() -> SseBulletin:
    return SseBulletin.model_validate(
        {
            "ADDDATE": "2021-11-21 15:30:12",
            "SECURITY_CODE": "688190",
            "SECURITY_NAME": "云路股份",
            "SSEDATE": "2021-11-22",
            "TITLE": "云路股份首次公开发行股票并在科创板上市招股说明书",
            "URL": "/disclosure/688190.pdf",
        }
    )
