"""Operator CLI for source-only historical industry admission."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console

from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.historical_industry_admission import admit_capco_membership
from ashare_lab.data.historical_industry_artifacts import (
    write_historical_industry_admission,
    write_historical_industry_calendar,
)
from ashare_lab.data.historical_industry_calendar_runtime import (
    load_historical_industry_calendar,
)
from ashare_lab.data.schema_registry import SchemaRegistry

_PROJECT_ROOT: Final = Path(__file__).parents[2]
app = typer.Typer(add_completion=False)


@app.command()
def run_historical_industry_admission(
    capco_membership_path: Annotated[
        Path,
        typer.Option(
            "--capco-membership",
            exists=True,
            dir_okay=False,
            help="Exact FOUND CAPCO membership manifest.",
        ),
    ],
    output_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Source-only artifact root."),
    ] = Path("artifacts/source_audits"),
) -> None:
    """Admit one exact CAPCO audit without writing research data or MongoDB."""
    report = CapcoMembershipAudit.model_validate_json(
        capco_membership_path.read_text(encoding="utf-8")
    )
    calendar = load_historical_industry_calendar(
        _PROJECT_ROOT,
        report.temporal_resolution.provider_publication_date,
    )
    registry = SchemaRegistry.load(_PROJECT_ROOT / "schemas" / "historical_industry_source_v1.json")
    admission = admit_capco_membership(
        report,
        registry,
        calendar=calendar,
        admitted_at=datetime.now(UTC),
    )
    calendar_artifact = write_historical_industry_calendar(
        calendar,
        output_root / "historical_industry_calendars",
    )
    admission_artifact = write_historical_industry_admission(
        admission,
        output_root / "historical_industry_admissions",
    )
    console = Console()
    console.print(f"calendar_artifact={calendar_artifact.path}")
    console.print(f"admission_id={admission.admission_id}")
    console.print(f"admission_artifact={admission_artifact.path}")
    console.print(f"available_at={admission.pit_candidate.available_at.isoformat()}")
    console.print(f"research_use_authorized={admission.research_use_authorized}")


def run() -> None:
    """Run the source-only historical industry admission command."""
    app()


if __name__ == "__main__":
    run()
