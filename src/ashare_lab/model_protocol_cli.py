"""CLI command for freezing the next model experiment before implementation."""

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
from ashare_lab.services.model_protocol_runtime import (
    ModelProtocolRuntimeError,
    run_default_model_preregistration,
)

_CONSOLE = Console()
_DATETIME_ADAPTER = TypeAdapter(datetime)


def model_preregister(
    diagnostic_report_id: Annotated[
        str,
        typer.Option(help="Exact post-hoc model_diagnostic content identity."),
    ],
    registered_at: Annotated[
        str,
        typer.Option(help="ISO-8601 protocol registration time with timezone offset."),
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
    """Preregister a rank-aligned experiment without training or holdout access."""
    try:
        run_research_preflight(
            PreflightRequest(project_root, "ashare_quant", require_clean_worktree=True)
        )
        descriptor = run_default_model_preregistration(
            project_root,
            diagnostic_report_id,
            _parse_registration_time(registered_at),
            registered_by,
        )
    except (ResearchPreflightError, ModelProtocolRuntimeError) as error:
        _CONSOLE.print(f"BLOCKED: {error}")
        raise typer.Exit(code=2) from error
    _CONSOLE.print(f"model protocol: {descriptor.protocol_id}")
    _CONSOLE.print("candidate: RIDGE_RANK_NOT_IMPLEMENTED")
    _CONSOLE.print("training: NOT_EXECUTED")
    _CONSOLE.print("final holdout: SEALED")


def _parse_registration_time(value: str) -> datetime:
    """Parse one explicit, offset-aware registration timestamp at the CLI boundary."""
    try:
        registered_at = _DATETIME_ADAPTER.validate_python(value)
    except ValidationError as error:
        detail = "registered_at must be an ISO-8601 timezone-aware datetime"
        raise ModelProtocolRuntimeError(detail) from error
    if registered_at.tzinfo is None or registered_at.utcoffset() is None:
        detail = "registered_at must be timezone-aware"
        raise ModelProtocolRuntimeError(detail)
    return registered_at
