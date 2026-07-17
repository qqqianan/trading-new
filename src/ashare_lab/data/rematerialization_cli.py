"""Operator command for offline governed lineage rematerialization."""

from rich.console import Console

from ashare_lab.data.rematerialization_runtime import (
    RematerializationTarget,
    rematerialize_target,
)

_CONSOLE = Console()


def rematerialize_lineage(target: RematerializationTarget) -> None:
    """Replay one bundle from immutable Raw and print aggregate counts."""
    result = rematerialize_target(target)
    _CONSOLE.print(
        f"rematerialized target={target.value} batches={result.batch_count} "
        f"records={result.record_count} canonical_inserted={result.canonical_inserted_count} "
        f"events={result.event_count} event_inserted={result.event_inserted_count}"
    )
