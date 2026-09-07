from datetime import UTC, date, datetime
from pathlib import Path

from typer.testing import CliRunner

from ashare_lab.cninfo_consistency_cli import app
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    ProspectusBridgeCandidate,
)

from .cninfo_prospectus_fixtures import prospectus_audit


def test_cli_builds_consistency_from_only_explicit_audit_paths(tmp_path: Path) -> None:
    # Given: exact retained success and empty observation manifests.
    candidate = ProspectusBridgeCandidate(
        parent_audit_id=f"cninfo_industry_bridge_audit_{'a' * 64}",
        symbol="688190.SH",
        listing_date=date(2021, 11, 26),
    )
    paths = tuple(
        _write_audit(
            tmp_path,
            index,
            prospectus_audit(
                candidate,
                observed_at=datetime(2026, 7, 27, 9 + index, tzinfo=UTC),
                found=index == 0,
                marker=chr(ord("a") + index),
            ),
        )
        for index in range(2)
    )
    output_root = tmp_path / "output"

    # When: the operator names both immutable observations explicitly.
    result = CliRunner().invoke(
        app,
        [
            "--audit",
            str(paths[0]),
            "--audit",
            str(paths[1]),
            "--output-root",
            str(output_root),
        ],
    )

    # Then: the fail-closed conclusion is persisted and reported.
    assert result.exit_code == 0
    assert "status=UNSTABLE" in result.stdout
    assert len(tuple(output_root.glob("*/manifest.json"))) == 1


def _write_audit(
    tmp_path: Path,
    index: int,
    audit: CninfoProspectusBridgeAudit,
) -> Path:
    path = tmp_path / f"audit-{index}.json"
    path.write_text(audit.model_dump_json(), encoding="utf-8")
    return path
