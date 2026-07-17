"""Operator command for offline governed lineage rematerialization."""

from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.data.rematerialization_runtime import (
    RematerializationTarget,
    rematerialize_target,
)

_CONSOLE = Console()


def rematerialize_lineage(
    target: RematerializationTarget,
    max_batches: Annotated[int, typer.Option(min=1, max=2_000)] = 500,
) -> None:
    """Replay one bundle from immutable Raw and print aggregate counts."""
    result = rematerialize_target(target, max_batches)
    _CONSOLE.print(
        f"rematerialized target={target.value} batches={result.batch_count} "
        f"records={result.record_count} canonical_inserted={result.canonical_inserted_count} "
        f"events={result.event_count} event_inserted={result.event_inserted_count}"
        f" skipped_completed={result.skipped_completed_count} has_more={result.has_more}"
    )
