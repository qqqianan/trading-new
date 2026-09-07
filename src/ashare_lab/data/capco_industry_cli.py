"""Operator command for read-only CAPCO industry archive audits."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.data.capco_industry_archives import (
    CapcoCoverageStatus,
    audit_capco_archive,
)
from ashare_lab.data.historical_industry_artifacts import write_capco_archive_audit
from ashare_lab.data.http_client import create_provider_client

_CONSOLE = Console()


def audit_capco_industry_archives(
    start_year: Annotated[int, typer.Option(min=2000, max=2100)] = 2023,
    end_year: Annotated[int, typer.Option(min=2000, max=2100)] = 2024,
    output_dir: Annotated[
        Path,
        typer.Option(file_okay=False, help="CAPCO source-audit artifact directory."),
    ] = Path("artifacts/source_audits/capco_historical_industry"),
) -> None:
    """Audit official CAPCO pages and PDFs without writing MongoDB."""
    with create_provider_client() as client:
        report = audit_capco_archive(
            client,
            start_year=start_year,
            end_year=end_year,
            audited_at=datetime.now(UTC),
        )
    artifact = write_capco_archive_audit(report, output_dir)
    found = sum(cell.status is CapcoCoverageStatus.FOUND for cell in report.coverage)
    missing = len(report.coverage) - found
    _CONSOLE.print(
        f"audit_id={report.audit_id} found={found} missing={missing} "
        f"research_use_authorized={report.research_use_authorized}"
    )
    _CONSOLE.print(f"artifact={artifact.path}")
