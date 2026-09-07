import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ashare_lab.data.capco_industry_archives import (
    CapcoArchiveEvidence,
    CapcoIndustryArchiveAudit,
)
from ashare_lab.data.capco_membership import (
    CapcoMembershipError,
    CapcoMembershipStatus,
    audit_capco_membership,
    build_capco_membership_candidate,
    parse_capco_membership,
)
from ashare_lab.data.capco_membership_models import CapcoPdfDocument
from ashare_lab.data.cninfo_industry_bridge import BridgeCandidate, CninfoIndustryBridgeAudit
from ashare_lab.data.historical_industry_artifacts import write_capco_membership_audit

LAYOUT_PAGE = """
                                                            计算机、通信和其他电
 688475   萤石网络     C      制造业        CH    电气、电子及通讯    39
                                                              子设备制造业
"""

ACTUAL_LAYOUT_PAGE = (
    "  688472   阿特斯       C        制造业          CH    电气、电子及通讯"
    "        38  电气机械和器材制造业\n"
    "  688475   萤石网络      C        制造业          CH    电气、电子及通讯"
    "        39  计算机、通信和其他电\n"
    "                                                                        子设备制造业\n"
)


class Provider:
    """In-memory CAPCO attachment provider."""

    def __init__(self, content: bytes = b"%PDF-capco") -> None:
        self.content = content

    def fetch_pdf(self, url: str) -> CapcoPdfDocument:
        return CapcoPdfDocument(url=url, content=self.content)


def test_capco_layout_parser_reconstructs_split_company_industry() -> None:
    # Given: one code-sorted CAPCO row whose final industry name wraps around the row.
    # When: the exact security is parsed from layout-preserving page text.
    parsed = parse_capco_membership((LAYOUT_PAGE,), "688475")

    # Then: section and division codes form the explicit company classification.
    assert parsed.security_name == "萤石网络"
    assert parsed.industry_code == "C39"
    assert parsed.industry_name == "计算机、通信和其他电子设备制造业"
    assert parsed.page_number == 1


def test_capco_layout_parser_reconstructs_actual_same_row_prefix() -> None:
    # Given: the exact layout shape emitted by pypdf for the official 2023 H1 PDF.
    # When: the target row and its continuation are parsed.
    parsed = parse_capco_membership((ACTUAL_LAYOUT_PAGE,), "688475")

    # Then: the same-row prefix and following continuation form the complete name.
    assert parsed.industry_code == "C39"
    assert parsed.industry_name == "计算机、通信和其他电子设备制造业"


def test_capco_layout_parser_rejects_duplicate_security_rows() -> None:
    # Given: the same security appears on two pages of one supposed code-sorted file.
    # When / Then: duplicate evidence cannot be selected by page order.
    with pytest.raises(CapcoMembershipError, match="exactly one"):
        parse_capco_membership((LAYOUT_PAGE, LAYOUT_PAGE), "688475")


def test_capco_candidate_binds_archive_and_prior_conflict() -> None:
    # Given: exact archive evidence and the unresolved IPO disclosure conflict.
    archive = _archive()
    conflict = _conflict()

    # When: the later-classification candidate is assembled.
    candidate = build_capco_membership_candidate(
        archive,
        conflict,
        year=2023,
        half=1,
    )

    # Then: both parents, publication date, and attachment hash are immutable inputs.
    assert candidate.parent_archive_audit_id == archive.audit_id
    assert candidate.parent_conflict_audit_id == conflict.audit_id
    assert candidate.publication_date == date(2024, 2, 8)
    assert candidate.expected_attachment_sha256 == "d" * 64


def test_capco_membership_audit_records_unknown_until_publication() -> None:
    # Given: one hash-matching official CAPCO attachment and layout text.
    content = b"%PDF-capco"
    candidate = build_capco_membership_candidate(
        _archive(attachment_hash=hashlib.sha256(content).hexdigest()),
        _conflict(),
        year=2023,
        half=1,
    )

    # When: the later official membership row is audited.
    report = audit_capco_membership(
        Provider(content),
        candidate,
        audited_at=datetime(2026, 7, 27, 16, tzinfo=UTC),
        page_extractor=lambda _content: (LAYOUT_PAGE,),
    )

    # Then: C39 is source evidence only after an explicit unknown interval.
    assert report.status is CapcoMembershipStatus.FOUND
    assert report.evidence is not None
    assert report.evidence.industry_code == "C39"
    assert report.temporal_resolution.unknown_from == date(2022, 12, 28)
    assert report.temporal_resolution.provider_publication_date == date(2024, 2, 8)
    assert report.temporal_resolution.availability_status == ("PENDING_NEXT_TRADING_SESSION_OPEN")
    assert report.research_use_authorized is False


def test_capco_membership_audit_rejects_attachment_hash_mismatch() -> None:
    # Given: downloaded bytes that differ from the parent archive evidence.
    candidate = build_capco_membership_candidate(_archive(), _conflict(), year=2023, half=1)

    # When: the exact attachment boundary is audited.
    report = audit_capco_membership(
        Provider(),
        candidate,
        audited_at=datetime(2026, 7, 27, 16, tzinfo=UTC),
    )

    # Then: no row parser can run against substituted bytes.
    assert report.status is CapcoMembershipStatus.MISSING
    assert report.failure_reason == "attachment_hash_mismatch"


def test_capco_membership_artifact_is_content_addressed(tmp_path: Path) -> None:
    # Given: a completed source-only membership audit.
    content = b"%PDF-capco"
    candidate = build_capco_membership_candidate(
        _archive(attachment_hash=hashlib.sha256(content).hexdigest()),
        _conflict(),
        year=2023,
        half=1,
    )
    report = audit_capco_membership(
        Provider(content),
        candidate,
        audited_at=datetime(2026, 7, 27, 16, tzinfo=UTC),
        page_extractor=lambda _content: (LAYOUT_PAGE,),
    )

    # When: the exact report is published.
    artifact = write_capco_membership_audit(report, tmp_path)

    # Then: its precomputed identity owns the immutable manifest.
    assert artifact.path == tmp_path / report.audit_id / "manifest.json"


def _archive(attachment_hash: str = "d" * 64) -> CapcoIndustryArchiveAudit:
    evidence = CapcoArchiveEvidence(
        year=2023,
        half=1,
        title="2023年上半年上市公司行业分类结果",
        page_url="https://www.capco.org.cn/archive.html",
        publication_date=date(2024, 2, 8),
        attachment_url="https://sp.capco.org.cn:82/2023h1.pdf",
        page_sha256="c" * 64,
        page_bytes=100,
        attachment_sha256=attachment_hash,
        attachment_bytes=1_100_930,
    )
    return CapcoIndustryArchiveAudit(
        audit_id=f"capco_industry_archive_audit_{'a' * 64}",
        audit_version="capco_archive_audit_v1",
        source="China Association for Public Companies",
        source_list_url="https://www.capco.org.cn/",
        start_year=2023,
        end_year=2024,
        audited_at=datetime(2026, 7, 23, 8, tzinfo=UTC),
        coverage=(),
        evidence=(evidence,),
        research_use_authorized=False,
    )


def _conflict() -> CninfoIndustryBridgeAudit:
    return CninfoIndustryBridgeAudit(
        audit_id=f"cninfo_industry_bridge_audit_{'b' * 64}",
        audit_version="cninfo_industry_bridge_audit_v4",
        audited_at=datetime(2026, 7, 24, 9, tzinfo=UTC),
        candidate=BridgeCandidate(symbol="688475.SH", listing_date=date(2022, 12, 28)),
        status="MISSING",
        failure_reason="explicit_industry_disclosure_conflicting",
        evidence=None,
        research_use_authorized=False,
    )
