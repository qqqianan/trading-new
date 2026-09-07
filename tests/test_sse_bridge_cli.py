import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx2
import pytest
from typer.testing import CliRunner

from ashare_lab import sse_bridge_cli
from ashare_lab.data.cninfo_observation_consistency import build_prospectus_consistency_audit
from ashare_lab.data.cninfo_prospectus_bridge import ProspectusBridgeCandidate

from .cninfo_prospectus_fixtures import prospectus_audit


def test_sse_cli_writes_fail_closed_source_audit_without_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an exact contradictory parent and wire-level SSE responses.
    parent_path = _write_parent(tmp_path)
    query = _query_payload()

    def respond(request: httpx2.Request) -> httpx2.Response:
        content = query if request.url.host == "query.sse.com.cn" else b"<html>blocked</html>"
        return httpx2.Response(200, content=content)

    def client_factory() -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(respond), follow_redirects=True)

    monkeypatch.setattr(sse_bridge_cli, "create_provider_client", client_factory)
    output_root = tmp_path / "output"

    # When: the operator runs the independent source audit.
    result = CliRunner().invoke(
        sse_bridge_cli.app,
        [
            "--parent-consistency",
            str(parent_path),
            "--output-root",
            str(output_root),
        ],
    )

    # Then: the attachment failure is persisted without research authority.
    assert result.exit_code == 0
    assert "status=MISSING" in result.stdout
    manifest = next(output_root.glob("*/manifest.json"))
    assert '"research_use_authorized": false' in manifest.read_text(encoding="utf-8")


def _write_parent(tmp_path: Path) -> Path:
    candidate = ProspectusBridgeCandidate(
        parent_audit_id=f"cninfo_industry_bridge_audit_{'a' * 64}",
        symbol="688190.SH",
        listing_date=date(2021, 11, 26),
    )
    parent = build_prospectus_consistency_audit(
        candidate,
        (
            prospectus_audit(
                candidate,
                observed_at=datetime(2026, 7, 27, 10, tzinfo=UTC),
                found=True,
                marker="a",
            ),
            prospectus_audit(
                candidate,
                observed_at=datetime(2026, 7, 27, 11, tzinfo=UTC),
                found=False,
                marker="b",
            ),
        ),
        assessed_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
    )
    path = tmp_path / "parent.json"
    path.write_text(parent.model_dump_json(), encoding="utf-8")
    return path


def _query_payload() -> bytes:
    return json.dumps(
        {
            "result": [
                {
                    "ADDDATE": "2021-11-21 15:30:12",
                    "SECURITY_CODE": "688190",
                    "SECURITY_NAME": "云路股份",
                    "SSEDATE": "2021-11-22",
                    "TITLE": "云路股份首次公开发行股票并在科创板上市招股说明书",
                    "URL": "/disclosure/document.pdf",
                }
            ]
        },
        ensure_ascii=False,
    ).encode()
