"""Operator CLI for the fixed 30-stock CNInfo industry bridge pilot."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from pymongo import MongoClient
from rich.console import Console

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeCandidate,
    CninfoIndustryBridgeAudit,
    audit_cninfo_candidate,
)
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    audit_cninfo_prospectus_candidate,
)
from ashare_lab.data.config import DataSettings
from ashare_lab.data.historical_industry_artifacts import (
    write_cninfo_bridge_audit,
    write_cninfo_prospectus_bridge_audit,
)
from ashare_lab.data.http_client import create_provider_client
from ashare_lab.data.official_bridge_candidates import MongoOfficialBridgeCandidateReader
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.sync_service import RequestPacer
from ashare_lab.services.cninfo_bridge_batch import (
    CninfoBridgeBatchAudit,
    build_cninfo_bridge_batch,
)
from ashare_lab.services.cninfo_bridge_batch_artifacts import (
    write_cninfo_bridge_batch,
    write_cninfo_bridge_selection,
    write_cninfo_prospectus_batch,
)
from ashare_lab.services.cninfo_bridge_sampling import select_stratified_candidates
from ashare_lab.services.cninfo_prospectus_batch import (
    build_cninfo_prospectus_batch,
    eligible_prospectus_candidates,
)

_START_DATE: Final = date(2021, 11, 10)
_END_EXCLUSIVE: Final = date(2024, 2, 8)
_EXPECTED_CANDIDATES: Final = 842
_SAMPLE_SIZE: Final = 30
_PARENT_BATCH_ID: Final = (
    "cninfo_bridge_batch_audit_ee8a426a3abe186a95b6834da53f3bcacde94c77eb5ae315e56fdbdc98e248ef"
)
_EXPECTED_PROSPECTUS_CANDIDATES: Final = 7


class PilotRuntimeError(Exception):
    """The governed source universe differs from the preregistered pilot."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one fail-closed runtime blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the pilot boundary and failure detail."""
        return f"cninfo_bridge_pilot: {self.detail}"


def run_pilot(
    project_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Project root containing the universe schema."),
    ] = Path(),
    output_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Source-audit artifact root."),
    ] = Path("artifacts/source_audits"),
) -> None:
    """Run the immutable 30-stock pilot without writing market data."""
    settings = DataSettings()
    schema_id = SchemaRegistry.load(
        project_root / "schemas" / "tushare_universe_v1.json"
    ).manifest_id
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        candidates = MongoOfficialBridgeCandidateReader(mongo[settings.mongodb_database]).read(
            _START_DATE, _END_EXCLUSIVE, schema_id
        )
    if len(candidates) != _EXPECTED_CANDIDATES:
        detail = f"expected {_EXPECTED_CANDIDATES} candidates, observed {len(candidates)}"
        raise PilotRuntimeError(detail)
    selection = select_stratified_candidates(candidates, sample_size=_SAMPLE_SIZE)
    selection_artifact = write_cninfo_bridge_selection(
        selection,
        output_root / "cninfo_bridge_selections",
    )
    audited_at = datetime.now(UTC)
    audits: list[CninfoIndustryBridgeAudit] = []
    console = Console()
    console.print(f"selection_id={selection.selection_id}")
    console.print(f"selection_artifact={selection_artifact.path}")
    with create_provider_client() as http:
        provider = CninfoArchiveClient(
            http,
            RequestPacer(settings.cninfo_min_request_interval_seconds),
        )
        for candidate in selection.selected:
            audit = audit_cninfo_candidate(
                provider,
                BridgeCandidate(symbol=candidate.symbol, listing_date=candidate.listing_date),
                audited_at=audited_at,
            )
            write_cninfo_bridge_audit(
                audit,
                output_root / "cninfo_industry_bridge",
            )
            audits.append(audit)
            console.print(f"symbol={candidate.symbol} status={audit.status.value}")
    report = build_cninfo_bridge_batch(selection, tuple(audits), audited_at=audited_at)
    artifact = write_cninfo_bridge_batch(
        report,
        output_root / "cninfo_bridge_batches",
    )
    console.print(
        f"batch_id={report.batch_id} found={report.found_count} missing={report.missing_count}"
    )
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")


def run_prospectus_pilot(
    parent_batch_path: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Exact v4 base batch manifest."),
    ],
    output_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Source-audit artifact root."),
    ] = Path("artifacts/source_audits"),
) -> None:
    """Supplement exact disclosure misses using full official prospectuses."""
    parent = CninfoBridgeBatchAudit.model_validate_json(parent_batch_path.read_text())
    if parent.batch_id != _PARENT_BATCH_ID:
        detail = f"unexpected parent batch: {parent.batch_id}"
        raise PilotRuntimeError(detail)
    candidates = eligible_prospectus_candidates(parent.audits)
    if len(candidates) != _EXPECTED_PROSPECTUS_CANDIDATES:
        detail = (
            f"expected {_EXPECTED_PROSPECTUS_CANDIDATES} prospectus candidates, "
            f"observed {len(candidates)}"
        )
        raise PilotRuntimeError(detail)
    audited_at = datetime.now(UTC)
    settings = DataSettings()
    audits: list[CninfoProspectusBridgeAudit] = []
    console = Console()
    with create_provider_client() as http:
        provider = CninfoArchiveClient(
            http,
            RequestPacer(settings.cninfo_min_request_interval_seconds),
        )
        for candidate in candidates:
            audit = audit_cninfo_prospectus_candidate(
                provider,
                candidate,
                audited_at=audited_at,
            )
            write_cninfo_prospectus_bridge_audit(
                audit,
                output_root / "cninfo_prospectus_bridge",
            )
            audits.append(audit)
            console.print(f"symbol={candidate.symbol} status={audit.status.value}")
    report = build_cninfo_prospectus_batch(
        parent.batch_id,
        candidates,
        tuple(audits),
        audited_at=audited_at,
    )
    artifact = write_cninfo_prospectus_batch(
        report,
        output_root / "cninfo_prospectus_batches",
    )
    console.print(
        f"batch_id={report.batch_id} found={report.found_count} missing={report.missing_count}"
    )
    console.print(f"artifact={artifact.path}")
    console.print(f"research_use_authorized={report.research_use_authorized}")


def run() -> None:
    """Run the operator command."""
    typer.run(run_pilot)


def run_prospectus() -> None:
    """Run the fixed prospectus supplemental operator command."""
    typer.run(run_prospectus_pilot)


if __name__ == "__main__":
    run()
