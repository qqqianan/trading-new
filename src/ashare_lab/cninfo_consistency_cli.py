"""Operator CLI for immutable CNInfo repeated-observation evidence."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.data.cninfo_observation_consistency import (
    build_prospectus_consistency_audit,
)
from ashare_lab.data.cninfo_prospectus_bridge import CninfoProspectusBridgeAudit
from ashare_lab.data.historical_industry_artifacts import (
    write_cninfo_prospectus_consistency_audit,
)

app = typer.Typer(add_completion=False)


@app.command()
def run_consistency(
    audit_paths: Annotated[
        list[Path],
        typer.Option(
            "--audit",
            exists=True,
            dir_okay=False,
            help="Exact prospectus audit manifest; repeat for every observation.",
        ),
    ],
    output_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Source-audit consistency artifact root."),
    ] = Path("artifacts/source_audits/cninfo_prospectus_consistency"),
) -> None:
    """Assess only the explicitly named immutable source observations."""
    audits = tuple(
        CninfoProspectusBridgeAudit.model_validate_json(path.read_text(encoding="utf-8"))
        for path in audit_paths
    )
    if not audits:
        detail = "at least one --audit manifest is required"
        raise typer.BadParameter(detail)
    report = build_prospectus_consistency_audit(
        audits[0].candidate,
        audits,
        assessed_at=datetime.now(UTC),
    )
    artifact = write_cninfo_prospectus_consistency_audit(report, output_root)
    console = Console()
    console.print(f"consistency_id={report.consistency_id}")
    console.print(f"status={report.status.value} reason={report.reason}")
    console.print(f"observations={len(report.observations)} artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")


def run() -> None:
    """Run the repeated-observation operator command."""
    app()


if __name__ == "__main__":
    run()
