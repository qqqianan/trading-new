"""CLI command for immutable development portfolio performance attribution."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.research.preflight import (
    PreflightRequest,
    ResearchPreflightError,
    run_research_preflight,
)
from ashare_lab.services.model_attribution_runtime import (
    ModelAttributionRuntimeError,
    run_model_performance_attribution,
)

_CONSOLE = Console()


def model_attribute(
    diagnostic_report_id: Annotated[
        str,
        typer.Option(help="Exact immutable model_diagnostic parent identity."),
    ],
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Publish development attribution without training or holdout access."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        descriptor = run_model_performance_attribution(project_root, diagnostic_report_id)
    except (ResearchPreflightError, ModelAttributionRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"model attribution: {descriptor.report_id}")
    _CONSOLE.print("scope: POST_HOC_DEVELOPMENT_ATTRIBUTION_ONLY")
    _CONSOLE.print("tuning: FORBIDDEN")
    _CONSOLE.print("final holdout: SEALED")
