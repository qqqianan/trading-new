"""Operator CLI for parent-linked CAPCO membership source audits."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.data.capco_client import CapcoArchiveClient
from ashare_lab.data.capco_industry_archives import CapcoIndustryArchiveAudit
from ashare_lab.data.capco_membership import (
    audit_capco_membership,
    build_capco_membership_candidate,
)
from ashare_lab.data.cninfo_industry_bridge import CninfoIndustryBridgeAudit
from ashare_lab.data.config import DataSettings
from ashare_lab.data.historical_industry_artifacts import write_capco_membership_audit
from ashare_lab.data.http_client import create_provider_client
from ashare_lab.data.sync_service import RequestPacer

app = typer.Typer(add_completion=False)


@app.command()
def run_capco_membership(
    parent_archive_path: Annotated[
        Path,
        typer.Option(
            "--parent-archive",
            exists=True,
            dir_okay=False,
            help="Exact CAPCO archive manifest.",
        ),
    ],
    parent_conflict_path: Annotated[
        Path,
        typer.Option(
            "--parent-conflict",
            exists=True,
            dir_okay=False,
            help="Exact unresolved CNInfo conflict manifest.",
        ),
    ],
    year: Annotated[int, typer.Option(min=2000, max=2100)],
    half: Annotated[int, typer.Option(min=1, max=2)],
    output_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="CAPCO membership source-audit root."),
    ] = Path("artifacts/source_audits/capco_memberships"),
) -> None:
    """Audit one later CAPCO row without constructing PIT availability."""
    archive = CapcoIndustryArchiveAudit.model_validate_json(
        parent_archive_path.read_text(encoding="utf-8")
    )
    conflict = CninfoIndustryBridgeAudit.model_validate_json(
        parent_conflict_path.read_text(encoding="utf-8")
    )
    candidate = build_capco_membership_candidate(archive, conflict, year=year, half=half)
    settings = DataSettings()
    with create_provider_client() as http:
        provider = CapcoArchiveClient(
            http,
            RequestPacer(settings.capco_min_request_interval_seconds),
        )
        report = audit_capco_membership(provider, candidate, audited_at=datetime.now(UTC))
    artifact = write_capco_membership_audit(report, output_root)
    console = Console()
    console.print(f"audit_id={report.audit_id}")
    console.print(f"status={report.status.value} reason={report.failure_reason}")
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")


def run() -> None:
    """Run the parent-linked CAPCO membership operator command."""
    app()


if __name__ == "__main__":
    run()
