"""CLI command for immutable development promotion evaluation."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.research.preflight import (
    PreflightRequest,
    ResearchPreflightError,
    run_research_preflight,
)
from ashare_lab.services.model_promotion_runtime import (
    ModelPromotionRuntimeError,
    run_default_model_promotion_evaluation,
)

_CONSOLE = Console()


def model_evaluate(
    protocol_id: Annotated[str, typer.Option(help="Exact model_protocol identity.")],
    model_id: Annotated[str, typer.Option(help="Exact governed ridge_model identity.")],
    diagnostic_report_id: Annotated[
        str,
        typer.Option(help="Exact model_diagnostic identity."),
    ],
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Publish frozen development gates without opening final holdout data."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        result = run_default_model_promotion_evaluation(
            project_root,
            protocol_id,
            model_id,
            diagnostic_report_id,
        )
    except (ResearchPreflightError, ModelPromotionRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"model promotion evaluation: {result.descriptor.evaluation_id}")
    _CONSOLE.print(f"development decision: {result.evaluation.decision.value}")
    _CONSOLE.print("model status: DRAFT")
    _CONSOLE.print("final holdout: SEALED")
