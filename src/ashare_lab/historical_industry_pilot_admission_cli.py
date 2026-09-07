"""Operator CLI for all-candidate historical-industry source admission."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console

from ashare_lab.data.historical_industry_artifacts import (
    write_historical_industry_admission_batch,
    write_historical_industry_calendar,
    write_historical_industry_pilot_admission,
)
from ashare_lab.data.historical_industry_calendar_runtime import (
    load_historical_industry_calendar,
)
from ashare_lab.data.historical_industry_pilot_admission import (
    admit_historical_industry_resolution,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionReport,
)
from ashare_lab.data.schema_registry import SchemaRegistry

_PROJECT_ROOT: Final = Path(__file__).parents[2]
_SOURCE_ROOT: Final = Path("artifacts/source_audits")
app = typer.Typer(add_completion=False)


@app.command()
def run_historical_industry_pilot_admission(
    resolution_path: Annotated[
        Path,
        typer.Option("--resolution", exists=True, dir_okay=False),
    ],
) -> None:
    """Admit every exact resolved row without writing MongoDB or research data."""
    resolution = HistoricalIndustryResolutionReport.model_validate_json(
        resolution_path.read_text(encoding="utf-8")
    )
    publication_dates = tuple(
        sorted(
            {
                row.source.provider_publication_date
                for row in resolution.rows
                if row.source.timestamp_precision == "DATE_ONLY"
            }
        )
    )
    calendars = tuple(
        load_historical_industry_calendar(_PROJECT_ROOT, publication_date)
        for publication_date in publication_dates
    )
    registry = SchemaRegistry.load(_PROJECT_ROOT / "schemas" / "historical_industry_source_v2.json")
    batch = admit_historical_industry_resolution(
        resolution,
        registry,
        calendars=calendars,
        admitted_at=datetime.now(UTC),
    )
    for calendar in calendars:
        write_historical_industry_calendar(
            calendar,
            _SOURCE_ROOT / "historical_industry_calendars",
        )
    for admission in batch.admissions:
        write_historical_industry_pilot_admission(
            admission,
            _SOURCE_ROOT / "historical_industry_pilot_admissions",
        )
    artifact = write_historical_industry_admission_batch(
        batch,
        _SOURCE_ROOT / "historical_industry_admission_batches",
    )
    console = Console()
    console.print(f"batch_id={batch.batch_id}")
    console.print(f"resolved_count={batch.resolved_count}")
    console.print(f"unknown_interval_count={batch.unknown_interval_count}")
    console.print(f"calendar_count={len(calendars)}")
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={batch.research_use_authorized}")


def run() -> None:
    """Run all-candidate source-only historical-industry admission."""
    app()


if __name__ == "__main__":
    run()
