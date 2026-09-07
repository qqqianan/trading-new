from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab import historical_industry_resolution_cli
from tests.test_historical_industry_resolution import _inputs


def test_resolution_cli_requires_and_persists_all_exact_parent_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: exact base, supplemental, consistency, SSE, and CAPCO manifests.
    base, supplemental, consistency, sse, capco = _inputs()
    paths = tuple(
        _write(tmp_path, name, model.model_dump_json())
        for name, model in (
            ("base", base),
            ("supplemental", supplemental),
            ("consistency", consistency),
            ("sse", sse),
            ("capco", capco),
        )
    )
    output_root = tmp_path / "output"
    monkeypatch.setattr(historical_industry_resolution_cli, "_OUTPUT_ROOT", output_root)

    # When: the operator resolves the fixed source protocol.
    result = CliRunner().invoke(
        historical_industry_resolution_cli.app,
        [
            "--base-batch",
            str(paths[0]),
            "--supplemental-batch",
            str(paths[1]),
            "--consistency",
            str(paths[2]),
            "--sse-audit",
            str(paths[3]),
            "--capco-audit",
            str(paths[4]),
        ],
    )

    # Then: all four candidates and source-only status are visible and immutable.
    assert result.exit_code == 0
    assert "resolved_count=4" in result.stdout
    assert "research_use_authorized=False" in result.stdout
    assert len(tuple(output_root.glob("*/manifest.json"))) == 1


def _write(root: Path, name: str, content: str) -> Path:
    path = root / f"{name}.json"
    path.write_text(content, encoding="utf-8")
    return path
