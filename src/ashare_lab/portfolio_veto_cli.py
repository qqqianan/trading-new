"""CLI command for protocol-bound factor-anchor Ridge-veto targets."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.research.preflight import (
    PreflightRequest,
    ResearchPreflightError,
    run_research_preflight,
)
from ashare_lab.services.portfolio_veto_runtime import (
    PortfolioVetoRuntimeError,
    run_factor_anchor_veto_targets,
)

_CONSOLE = Console()


def portfolio_veto_targets(
    protocol_id: Annotated[
        str,
        typer.Option(help="Exact portfolio_protocol implementation identity."),
    ],
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Publish pre-risk targets from reused development evidence only."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        descriptor = run_factor_anchor_veto_targets(project_root, protocol_id)
    except (ResearchPreflightError, PortfolioVetoRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"portfolio veto targets: {descriptor.artifact_id}")
    _CONSOLE.print("evidence: REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE")
    _CONSOLE.print("risk execution: REQUIRED_IN_BACKTEST")
    _CONSOLE.print("orders: NOT_CREATED")
    _CONSOLE.print("final holdout: FORBIDDEN")
