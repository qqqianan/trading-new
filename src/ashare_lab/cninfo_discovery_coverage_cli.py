"""Explicit-file CLI boundary for discovery completeness reports."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection
from ashare_lab.services.cninfo_discovery_coverage import build_discovery_coverage
from ashare_lab.services.cninfo_full_discovery import (
    CninfoFullDiscoveryPlan,
    CninfoFullDiscoveryShard,
)
from ashare_lab.services.cninfo_full_discovery_artifacts import write_discovery_coverage


def discovery_coverage(
    selection_path: Annotated[Path, typer.Option("--selection", exists=True, dir_okay=False)],
    plan_path: Annotated[Path, typer.Option("--plan", exists=True, dir_okay=False)],
    shard_paths: Annotated[list[Path], typer.Option("--shard", exists=True, dir_okay=False)],
    output_root: Annotated[Path, typer.Option(file_okay=False)] = Path(
        "artifacts/source_audits/cninfo_discovery_coverage"
    ),
) -> None:
    """Verify only explicitly supplied shards against one frozen selection and plan."""
    with selection_path.open(encoding="utf-8") as stream:
        selection = StratifiedCandidateSelection.model_validate_json(stream.read())
    with plan_path.open(encoding="utf-8") as stream:
        plan = CninfoFullDiscoveryPlan.model_validate_json(stream.read())
    shards: list[CninfoFullDiscoveryShard] = []
    for path in shard_paths:
        with path.open(encoding="utf-8") as stream:
            shards.append(CninfoFullDiscoveryShard.model_validate_json(stream.read()))
    report = build_discovery_coverage(selection, plan, tuple(shards))
    artifact = write_discovery_coverage(report, output_root)
    console = Console()
    console.print(f"status={report.status} observed={report.observed_count}")
    console.print(f"selected={report.selected_count} missing={report.missing_count}")
    console.print(f"unobserved={report.unobserved_count}")
    console.print(f"report_id={report.report_id}")
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")
