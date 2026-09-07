"""Operator CLI for recoverable full-population CNInfo discovery."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from pymongo import MongoClient
from rich.console import Console

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_listing_discovery import (
    CninfoListingDiscoveryAudit,
    discover_cninfo_listing,
)
from ashare_lab.data.config import DataSettings
from ashare_lab.data.http_client import create_provider_client
from ashare_lab.data.official_bridge_candidates import (
    MongoOfficialBridgeCandidateReader,
)
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.sync_service import RequestPacer
from ashare_lab.services.cninfo_bridge_batch_artifacts import (
    write_cninfo_bridge_selection,
)
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection
from ashare_lab.services.cninfo_full_discovery import (
    CninfoFullDiscoveryError,
    CninfoFullDiscoveryPlan,
    build_full_discovery_plan,
    build_full_discovery_shard,
    freeze_full_candidate_selection,
)
from ashare_lab.services.cninfo_full_discovery_artifacts import (
    write_full_discovery_plan,
    write_full_discovery_shard,
    write_listing_discovery_audit,
)

_START_DATE: Final = date(2021, 11, 10)
_END_EXCLUSIVE: Final = date(2024, 2, 8)
_EXPECTED_CANDIDATES: Final = 842
_SHARD_SIZE: Final = 50
_PILOT_EVIDENCE_CUTOFF: Final = datetime(
    2026,
    7,
    24,
    9,
    5,
    22,
    696495,
    tzinfo=UTC,
)
app = typer.Typer(add_completion=False)


def _expected_universe_sha256() -> str:
    return "5cb0161923ef3abcf9f13b478a15ff55c584b20570721b7426df6db1dff6ed62"


@app.command("plan")
def plan_full_discovery(
    project_root: Annotated[Path, typer.Option(file_okay=False)] = Path(),
    output_root: Annotated[Path, typer.Option(file_okay=False)] = Path("artifacts/source_audits"),
) -> None:
    """Freeze the exact 842-stock selection and shard plan before network access."""
    settings = DataSettings()
    schema_id = SchemaRegistry.load(
        project_root / "schemas" / "tushare_universe_v1.json"
    ).manifest_id
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        candidates = MongoOfficialBridgeCandidateReader(mongo[settings.mongodb_database]).read(
            _START_DATE,
            _END_EXCLUSIVE,
            schema_id,
            ingested_before=_PILOT_EVIDENCE_CUTOFF,
        )
    if len(candidates) != _EXPECTED_CANDIDATES:
        detail = f"expected {_EXPECTED_CANDIDATES} candidates, observed {len(candidates)}"
        raise CninfoFullDiscoveryError(detail)
    selection = freeze_full_candidate_selection(candidates)
    if selection.candidate_universe_sha256 != _expected_universe_sha256():
        detail = "candidate universe hash differs from the frozen 842-stock population"
        raise CninfoFullDiscoveryError(detail)
    selection_artifact = write_cninfo_bridge_selection(
        selection,
        output_root / "cninfo_bridge_selections",
    )
    plan = build_full_discovery_plan(
        selection,
        shard_size=_SHARD_SIZE,
        planned_at=datetime.now(UTC),
    )
    plan_artifact = write_full_discovery_plan(
        plan,
        output_root / "cninfo_full_discovery_plans",
    )
    console = Console()
    console.print(f"selection_id={selection.selection_id}")
    console.print(f"plan_id={plan.plan_id}")
    console.print(f"candidate_count={plan.candidate_count}")
    console.print(f"shard_count={len(plan.shards)}")
    console.print(f"selection_artifact={selection_artifact.path}")
    console.print(f"plan_artifact={plan_artifact.path}")
    console.print(f"research_use_authorized={plan.research_use_authorized}")


@app.command("run-shard")
def run_discovery_shard(
    selection_path: Annotated[
        Path,
        typer.Option("--selection", exists=True, dir_okay=False),
    ],
    plan_path: Annotated[
        Path,
        typer.Option("--plan", exists=True, dir_okay=False),
    ],
    shard_index: Annotated[int, typer.Option("--shard-index", min=0)],
    output_root: Annotated[Path, typer.Option(file_okay=False)] = Path("artifacts/source_audits"),
) -> None:
    """Run one exact discovery shard without downloading selected PDFs."""
    selection = StratifiedCandidateSelection.model_validate_json(
        selection_path.read_text(encoding="utf-8")
    )
    plan = CninfoFullDiscoveryPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    if plan.selection_id != selection.selection_id or shard_index >= len(plan.shards):
        detail = "explicit selection, plan, or shard index differs"
        raise CninfoFullDiscoveryError(detail)
    spec = plan.shards[shard_index]
    candidates = selection.selected[spec.start_offset : spec.end_offset_exclusive]
    discovered_at = datetime.now(UTC)
    audits: list[CninfoListingDiscoveryAudit] = []
    settings = DataSettings()
    console = Console()
    with create_provider_client() as http:
        provider = CninfoArchiveClient(
            http,
            RequestPacer(settings.cninfo_min_request_interval_seconds),
        )
        for candidate in candidates:
            audit = discover_cninfo_listing(
                provider,
                candidate,
                discovered_at=discovered_at,
            )
            write_listing_discovery_audit(
                audit,
                output_root / "cninfo_listing_discoveries",
            )
            audits.append(audit)
            console.print(f"symbol={candidate.symbol} status={audit.status.value}")
    shard = build_full_discovery_shard(
        plan,
        selection,
        shard_index=shard_index,
        audits=tuple(audits),
        completed_at=datetime.now(UTC),
    )
    artifact = write_full_discovery_shard(
        shard,
        output_root / "cninfo_full_discovery_shards",
    )
    console.print(
        f"shard_id={shard.shard_id} selected={shard.selected_count} missing={shard.missing_count}"
    )
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={shard.research_use_authorized}")


def run() -> None:
    """Run the full discovery operator group."""
    app()


if __name__ == "__main__":
    run()
