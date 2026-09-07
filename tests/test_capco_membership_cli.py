from datetime import UTC, date, datetime
from pathlib import Path

import httpx2
import pytest
from typer.testing import CliRunner

from ashare_lab import capco_membership_cli
from ashare_lab.data.capco_industry_archives import (
    CapcoArchiveEvidence,
    CapcoIndustryArchiveAudit,
)
from ashare_lab.data.cninfo_industry_bridge import BridgeCandidate, CninfoIndustryBridgeAudit


def test_capco_membership_cli_persists_fail_closed_source_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: exact parent manifests and substituted bytes at the registered URL.
    archive_path, conflict_path = _write_parents(tmp_path)

    def respond(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"%PDF-substituted")

    def client_factory() -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(respond))

    monkeypatch.setattr(capco_membership_cli, "create_provider_client", client_factory)
    output_root = tmp_path / "output"

    # When: the operator audits the exact 2023 H1 membership file.
    result = CliRunner().invoke(
        capco_membership_cli.app,
        [
            "--parent-archive",
            str(archive_path),
            "--parent-conflict",
            str(conflict_path),
            "--year",
            "2023",
            "--half",
            "1",
            "--output-root",
            str(output_root),
        ],
    )

    # Then: the mismatch remains auditable and cannot authorize research use.
    assert result.exit_code == 0
    assert "status=MISSING reason=attachment_hash_mismatch" in result.stdout
    manifest = next(output_root.glob("*/manifest.json"))
    assert '"research_use_authorized": false' in manifest.read_text(encoding="utf-8")


def _write_parents(tmp_path: Path) -> tuple[Path, Path]:
    archive = CapcoIndustryArchiveAudit(
        audit_id=f"capco_industry_archive_audit_{'a' * 64}",
        audit_version="capco_archive_audit_v1",
        source="China Association for Public Companies",
        source_list_url="https://www.capco.org.cn/",
        start_year=2023,
        end_year=2024,
        audited_at=datetime(2026, 7, 23, 8, tzinfo=UTC),
        coverage=(),
        evidence=(
            CapcoArchiveEvidence(
                year=2023,
                half=1,
                title="2023年上半年上市公司行业分类结果",
                page_url="https://www.capco.org.cn/archive.html",
                publication_date=date(2024, 2, 8),
                attachment_url="https://sp.capco.org.cn:82/2023h1.pdf",
                page_sha256="c" * 64,
                page_bytes=100,
                attachment_sha256="d" * 64,
                attachment_bytes=1_100_930,
            ),
        ),
        research_use_authorized=False,
    )
    conflict = CninfoIndustryBridgeAudit(
        audit_id=f"cninfo_industry_bridge_audit_{'b' * 64}",
        audit_version="cninfo_industry_bridge_audit_v4",
        audited_at=datetime(2026, 7, 24, 9, tzinfo=UTC),
        candidate=BridgeCandidate(symbol="688475.SH", listing_date=date(2022, 12, 28)),
        status="MISSING",
        failure_reason="explicit_industry_disclosure_conflicting",
        evidence=None,
        research_use_authorized=False,
    )
    archive_path = tmp_path / "archive.json"
    conflict_path = tmp_path / "conflict.json"
    archive_path.write_text(archive.model_dump_json(), encoding="utf-8")
    conflict_path.write_text(conflict.model_dump_json(), encoding="utf-8")
    return archive_path, conflict_path
