"""Operator CLI for evidence-derived dataset qualification."""

from datetime import date
from typing import Annotated

import typer
from pydantic import TypeAdapter
from rich.console import Console

from ashare_lab.research.datasets.coverage import QualificationStatus
from ashare_lab.services.dataset_coverage_runtime import qualify_default_dataset

app = typer.Typer(no_args_is_help=True, help="Governed dataset coverage for ashare_quant.")
_CONSOLE = Console()
_DATE_ADAPTER = TypeAdapter(date)


@app.command("qualify")
def qualify(
    start_date: Annotated[str, typer.Option(help="Inclusive date in YYYY-MM-DD format.")],
    end_date: Annotated[str, typer.Option(help="Inclusive date in YYYY-MM-DD format.")],
    require_industry: Annotated[  # noqa: FBT002
        bool,
        typer.Option(help="Require PIT industry coverage for the whole interval."),
    ] = False,
) -> None:
    """Persist the component matrix and a manifest only when evidence qualifies."""
    run = qualify_default_dataset(
        _DATE_ADAPTER.validate_python(start_date),
        _DATE_ADAPTER.validate_python(end_date),
        require_industry=require_industry,
    )
    _CONSOLE.print(
        f"coverage report={run.report.report_id} status={run.report.status.value} "
        f"start={run.report.qualified_start} end={run.report.qualified_end} "
        f"manifest={run.manifest.manifest_id if run.manifest is not None else 'none'} "
        f"blockers={','.join(run.report.blockers) if run.report.blockers else 'none'}"
    )
    if run.report.status is QualificationStatus.BLOCKED:
        raise typer.Exit(code=2)


def run() -> None:
    """Launch the coverage command group."""
    app()


if __name__ == "__main__":
    run()
