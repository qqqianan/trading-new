"""CLI command for preregistering the factor-anchor Ridge-veto portfolio."""

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import TypeAdapter, ValidationError
from rich.console import Console

from ashare_lab.research.preflight import (
    PreflightRequest,
    ResearchPreflightError,
    run_research_preflight,
)
from ashare_lab.services.portfolio_protocol_runtime import (
    PortfolioProtocolRuntimeError,
    run_factor_anchor_veto_preregistration,
)

_CONSOLE = Console()
_DATETIME_ADAPTER = TypeAdapter(datetime)


def portfolio_preregister(
    attribution_report_id: Annotated[
        str,
        typer.Option(help="Exact model_attribution parent identity."),
    ],
    registered_at: Annotated[
        str,
        typer.Option(help="ISO-8601 registration time with timezone offset."),
    ],
    registered_by: Annotated[
        str,
        typer.Option(help="Research owner freezing this protocol."),
    ] = "research_owner",
    project_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, resolve_path=True),
    ] = Path(),
) -> None:
    """Freeze the rule without building targets, training, or opening holdout."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        descriptor = run_factor_anchor_veto_preregistration(
            project_root,
            attribution_report_id,
            _parse_registration_time(registered_at),
            registered_by,
        )
    except (ResearchPreflightError, PortfolioProtocolRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"portfolio protocol: {descriptor.protocol_id}")
    _CONSOLE.print("candidate: NOT_IMPLEMENTED")
    _CONSOLE.print("reused development: NOT_OUT_OF_SAMPLE")
    _CONSOLE.print("fresh forward: REQUIRED_26_DECISION_DATES")
    _CONSOLE.print("final holdout: FORBIDDEN")


def _parse_registration_time(value: str) -> datetime:
    """Parse one explicit offset-aware registration timestamp."""
    try:
        registered_at = _DATETIME_ADAPTER.validate_python(value)
    except ValidationError as error:
        detail = "registered_at must be an ISO-8601 timezone-aware datetime"
        raise PortfolioProtocolRuntimeError(detail) from error
    if registered_at.tzinfo is None or registered_at.utcoffset() is None:
        detail = "registered_at must be timezone-aware"
        raise PortfolioProtocolRuntimeError(detail)
    return registered_at
