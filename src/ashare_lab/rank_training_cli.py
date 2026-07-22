"""CLI command for protocol-bound development rank Ridge training."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.research.preflight import (
    PreflightRequest,
    ResearchPreflightError,
    run_research_preflight,
)
from ashare_lab.services.rank_training_runtime import (
    RankTrainingRuntimeError,
    run_default_rank_ridge_training,
)

_CONSOLE = Console()


def train_ridge_rank(
    protocol_id: Annotated[
        str,
        typer.Option(help="Exact preregistered model_protocol content identity."),
    ],
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Fit rank-label Ridge on development data without opening final holdout."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        result = run_default_rank_ridge_training(project_root, protocol_id)
    except (ResearchPreflightError, RankTrainingRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"rank Ridge model: {result.artifact.model_id}")
    _CONSOLE.print(f"protocol: {protocol_id}")
    _CONSOLE.print("model status: DRAFT")
    _CONSOLE.print("final holdout: SEALED")
