"""Operator CLI for deterministic historical-industry source resolution."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console

from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.cninfo_observation_models import CninfoProspectusConsistencyAudit
from ashare_lab.data.historical_industry_artifacts import (
    write_historical_industry_resolution,
)
from ashare_lab.data.historical_industry_resolution import (
    HistoricalIndustryResolutionInputs,
    resolve_historical_industry_pilot,
)
from ashare_lab.data.sse_industry_models import SseProspectusIndustryAudit
from ashare_lab.services.cninfo_bridge_batch import CninfoBridgeBatchAudit
from ashare_lab.services.cninfo_prospectus_batch import CninfoProspectusBatchAudit

app = typer.Typer(add_completion=False)
_OUTPUT_ROOT: Final = Path("artifacts/source_audits/historical_industry_resolutions")


@app.command()
def run_historical_industry_resolution(
    base_batch_path: Annotated[Path, typer.Option("--base-batch", exists=True, dir_okay=False)],
    supplemental_batch_path: Annotated[
        Path, typer.Option("--supplemental-batch", exists=True, dir_okay=False)
    ],
    consistency_path: Annotated[Path, typer.Option("--consistency", exists=True, dir_okay=False)],
    sse_audit_path: Annotated[Path, typer.Option("--sse-audit", exists=True, dir_okay=False)],
    capco_audit_path: Annotated[Path, typer.Option("--capco-audit", exists=True, dir_okay=False)],
) -> None:
    """Resolve the fixed pilot without scanning for newer or successful artifacts."""
    inputs = HistoricalIndustryResolutionInputs(
        base=CninfoBridgeBatchAudit.model_validate_json(
            base_batch_path.read_text(encoding="utf-8")
        ),
        supplemental=CninfoProspectusBatchAudit.model_validate_json(
            supplemental_batch_path.read_text(encoding="utf-8")
        ),
        consistencies=(
            CninfoProspectusConsistencyAudit.model_validate_json(
                consistency_path.read_text(encoding="utf-8")
            ),
        ),
        sse_audits=(
            SseProspectusIndustryAudit.model_validate_json(
                sse_audit_path.read_text(encoding="utf-8")
            ),
        ),
        capco_audits=(
            CapcoMembershipAudit.model_validate_json(capco_audit_path.read_text(encoding="utf-8")),
        ),
    )
    report = resolve_historical_industry_pilot(
        inputs,
        resolved_at=datetime.now(UTC),
    )
    artifact = write_historical_industry_resolution(report, _OUTPUT_ROOT)
    console = Console()
    console.print(f"resolution_id={report.resolution_id}")
    console.print(f"resolved_count={report.resolved_count}")
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")


def run() -> None:
    """Run the fixed pilot historical-industry source resolution command."""
    app()


if __name__ == "__main__":
    run()
