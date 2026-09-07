"""Operator command for read-only historical industry source audits."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.data.historical_industry_archives import (
    ArchiveCoverageStatus,
    audit_csrc_archive,
)
from ashare_lab.data.historical_industry_artifacts import write_archive_audit
from ashare_lab.data.http_client import create_provider_client

_CONSOLE = Console()


def audit_historical_industry_archives(
    start_year: Annotated[int, typer.Option(min=2000, max=2100)] = 2020,
    end_year: Annotated[int, typer.Option(min=2000, max=2100)] = 2024,
    output_dir: Annotated[
        Path,
        typer.Option(file_okay=False, help="Source-audit artifact directory."),
    ] = Path("artifacts/source_audits/historical_industry"),
) -> None:
    """Audit official pages and PDFs without writing the research database."""
    with create_provider_client() as client:
        report = audit_csrc_archive(
            client,
            start_year=start_year,
            end_year=end_year,
            audited_at=datetime.now(UTC),
        )
    artifact = write_archive_audit(report, output_dir)
    found = sum(cell.status is ArchiveCoverageStatus.FOUND for cell in report.coverage)
    missing = len(report.coverage) - found
    _CONSOLE.print(
        f"audit_id={report.audit_id} found={found} missing={missing} "
        f"research_use_authorized={report.research_use_authorized}"
    )
    _CONSOLE.print(f"artifact={artifact.path}")
