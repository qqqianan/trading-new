"""Operator command for read-only CNInfo IPO industry bridge audits."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ashare_lab.data.cninfo_client import CninfoArchiveClient
from ashare_lab.data.cninfo_industry_bridge import BridgeCandidate, audit_cninfo_candidate
from ashare_lab.data.config import DataSettings
from ashare_lab.data.historical_industry_artifacts import write_cninfo_bridge_audit
from ashare_lab.data.http_client import create_provider_client
from ashare_lab.data.sync_service import RequestPacer

_CONSOLE = Console()


def audit_cninfo_industry_bridge(
    symbol: Annotated[str, typer.Option(help="A-share symbol with exchange suffix.")],
    listing_date: Annotated[str, typer.Option(help="Historical listing date in YYYY-MM-DD.")],
    output_dir: Annotated[
        Path,
        typer.Option(file_okay=False, help="CNInfo source-audit artifact directory."),
    ] = Path("artifacts/source_audits/cninfo_industry_bridge"),
) -> None:
    """Audit one official IPO disclosure without writing MongoDB."""
    candidate = BridgeCandidate(symbol=symbol, listing_date=date.fromisoformat(listing_date))
    settings = DataSettings()
    with create_provider_client() as http:
        provider = CninfoArchiveClient(
            http,
            RequestPacer(settings.cninfo_min_request_interval_seconds),
        )
        report = audit_cninfo_candidate(provider, candidate, audited_at=datetime.now(UTC))
    artifact = write_cninfo_bridge_audit(report, output_dir)
    _CONSOLE.print(
        f"symbol={symbol} status={report.status.value} "
        f"research_use_authorized={report.research_use_authorized}"
    )
    _CONSOLE.print(f"audit_id={report.audit_id}")
    _CONSOLE.print(f"artifact={artifact.path}")
