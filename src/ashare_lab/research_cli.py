"""Operator CLI for the auditable medium-horizon research workflow."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.research.preflight import (
    PreflightRequest,
    ResearchPreflightError,
    run_research_preflight,
)
from ashare_lab.research.workflow_runtime import (
    DryRunResearchPipeline,
    WorkflowRuntimeError,
    load_dry_run_request,
)
from ashare_lab.research.workflow_store import ResearchReportStore
from ashare_lab.services.factor_diagnostic_runtime import (
    FactorDiagnosticRuntimeError,
    run_default_factor_diagnostics,
)
from ashare_lab.services.portfolio_backtest_runtime import (
    PortfolioBacktestRuntimeError,
    run_default_portfolio_backtest,
)
from ashare_lab.services.portfolio_runtime import (
    PortfolioRuntimeError,
    run_default_portfolio_targets,
)
from ashare_lab.services.research_workflow import ResearchWorkflowService

app = typer.Typer(no_args_is_help=True, help="Auditable medium-horizon A-share research.")
_CONSOLE = Console()


@app.callback()
def research_cli() -> None:
    """Expose governed research commands without a bypassing root action."""


@app.command("dry-run")
def dry_run(
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
    output_dir: Annotated[
        Path,
        typer.Option(file_okay=False, resolve_path=True),
    ] = Path("data/research_reports"),
) -> None:
    """Write the complete ordered plan without data reads, backtest, or training."""
    try:
        identity = run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=False)
        )
        request = load_dry_run_request(project_root, identity)
        report = ResearchWorkflowService(DryRunResearchPipeline()).run(request)
        descriptor = ResearchReportStore(output_dir).write(report)
    except (ResearchPreflightError, WorkflowRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"report: {descriptor.report_id}")
    _CONSOLE.print("final holdout: SEALED")
    _CONSOLE.print("training: NOT_EXECUTED")


@app.command("diagnose")
def diagnose(
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Publish all real development diagnostics from a clean frozen repository."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        descriptor = run_default_factor_diagnostics(project_root)
    except (ResearchPreflightError, FactorDiagnosticRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"factor report: {descriptor.report_id}")
    _CONSOLE.print("final holdout: SEALED")


@app.command("portfolio")
def portfolio(
    factor_report_id: Annotated[
        str,
        typer.Option(help="Exact accepted factor_report content identity."),
    ],
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Publish label-free development Top 30 targets from one exact factor report."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        descriptor = run_default_portfolio_targets(project_root, factor_report_id)
    except (ResearchPreflightError, PortfolioRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"portfolio targets: {descriptor.artifact_id}")
    _CONSOLE.print("risk execution: REQUIRED_IN_BACKTEST")
    _CONSOLE.print("final holdout: SEALED")


@app.command("backtest")
def backtest(
    portfolio_target_id: Annotated[
        str,
        typer.Option(help="Exact portfolio_targets content identity."),
    ],
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Publish one risk-governed real development portfolio backtest."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        descriptor = run_default_portfolio_backtest(project_root, portfolio_target_id)
    except (ResearchPreflightError, PortfolioBacktestRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"portfolio backtest: {descriptor.report_id}")
    _CONSOLE.print("portfolio risk engine: ENFORCED")
    _CONSOLE.print("final holdout: SEALED")


def run() -> None:
    """Run the Typer application."""
    app()
