"""Operator CLI for independent SSE prospectus source audits."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.data.cninfo_observation_models import CninfoProspectusConsistencyAudit
from ashare_lab.data.config import DataSettings
from ashare_lab.data.historical_industry_artifacts import (
    write_sse_prospectus_industry_audit,
)
from ashare_lab.data.http_client import create_provider_client
from ashare_lab.data.sse_client import SseArchiveClient
from ashare_lab.data.sse_industry_bridge import (
    audit_sse_prospectus_candidate,
    candidate_from_cninfo_consistency,
)
from ashare_lab.data.sync_service import RequestPacer

app = typer.Typer(add_completion=False)


@app.command()
def run_sse_prospectus(
    parent_consistency_path: Annotated[
        Path,
        typer.Option(
            "--parent-consistency",
            exists=True,
            dir_okay=False,
            help="Exact unstable CNInfo consistency manifest.",
        ),
    ],
    output_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Independent SSE source-audit root."),
    ] = Path("artifacts/source_audits/sse_prospectus_industry"),
) -> None:
    """Confirm one exact CNInfo contradiction through the official SSE archive."""
    parent = CninfoProspectusConsistencyAudit.model_validate_json(
        parent_consistency_path.read_text(encoding="utf-8")
    )
    candidate = candidate_from_cninfo_consistency(parent)
    settings = DataSettings()
    with create_provider_client() as http:
        provider = SseArchiveClient(
            http,
            RequestPacer(settings.sse_min_request_interval_seconds),
        )
        report = audit_sse_prospectus_candidate(
            provider,
            candidate,
            audited_at=datetime.now(UTC),
        )
    artifact = write_sse_prospectus_industry_audit(report, output_root)
    console = Console()
    console.print(f"audit_id={report.audit_id}")
    console.print(f"status={report.status.value} reason={report.failure_reason}")
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")


def run() -> None:
    """Run the official SSE independent-source operator command."""
    app()


if __name__ == "__main__":
    run()
