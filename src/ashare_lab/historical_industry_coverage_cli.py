"""Operator CLI for historical-industry source coverage decisions."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import TypeAdapter
from rich.console import Console

from ashare_lab.data.historical_industry_artifacts import (
    write_historical_industry_coverage_report,
)
from ashare_lab.data.historical_industry_coverage import (
    HistoricalIndustryCoverageEvaluation,
    evaluate_historical_industry_coverage,
)
from ashare_lab.data.historical_industry_pilot_models import PilotIndustryAdmissionBatch
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionReport,
)
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection

_SOURCE_ROOT: Final = Path("artifacts/source_audits")
app = typer.Typer(add_completion=False)


@app.command()
def run_historical_industry_coverage(
    selection_path: Annotated[
        Path,
        typer.Option("--selection", exists=True, dir_okay=False),
    ],
    resolution_path: Annotated[
        Path,
        typer.Option("--resolution", exists=True, dir_okay=False),
    ],
    admission_batch_path: Annotated[
        Path,
        typer.Option("--admission-batch", exists=True, dir_okay=False),
    ],
    coverage_start: Annotated[str, typer.Option("--coverage-start")],
    coverage_end_exclusive: Annotated[
        str,
        typer.Option("--coverage-end-exclusive"),
    ],
) -> None:
    """Evaluate explicit source-only parents without publishing research data."""
    selection = StratifiedCandidateSelection.model_validate_json(
        selection_path.read_text(encoding="utf-8")
    )
    resolution = HistoricalIndustryResolutionReport.model_validate_json(
        resolution_path.read_text(encoding="utf-8")
    )
    batch = PilotIndustryAdmissionBatch.model_validate_json(
        admission_batch_path.read_text(encoding="utf-8")
    )
    datetime_adapter = TypeAdapter(datetime)
    report = evaluate_historical_industry_coverage(
        selection,
        resolution,
        batch,
        HistoricalIndustryCoverageEvaluation(
            coverage_start=datetime_adapter.validate_python(coverage_start),
            coverage_end_exclusive=datetime_adapter.validate_python(coverage_end_exclusive),
            evaluated_at=datetime.now(UTC),
        ),
    )
    artifact = write_historical_industry_coverage_report(
        report,
        _SOURCE_ROOT / "historical_industry_coverage_reports",
    )
    console = Console()
    console.print(f"report_id={report.report_id}")
    console.print(f"decision={report.decision.value}")
    console.print(f"population_count={report.population_count}")
    console.print(f"admitted_selected_count={report.admitted_selected_count}")
    console.print(f"population_missing_count={report.population_missing_count}")
    console.print(f"conflict_count={len(report.conflicting_admission_symbols)}")
    console.print(f"unknown_interval_count={len(report.unknown_intervals)}")
    console.print(f"blocking_reasons={','.join(report.blocking_reasons)}")
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")


def run() -> None:
    """Run the explicit historical-industry coverage gate."""
    app()


if __name__ == "__main__":
    run()
