"""Operator CLI for isolated Tushare Raw ingestion."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from pymongo import MongoClient
from rich.console import Console

from ashare_lab.data.balance_sheet_cli import backfill_balance_sheet
from ashare_lab.data.benchmark_cli import (
    backfill_benchmark_daily,
    backfill_benchmark_weights,
    sync_benchmark_master,
)
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical_store import MongoCanonicalStore
from ashare_lab.data.capco_industry_cli import audit_capco_industry_archives
from ashare_lab.data.cashflow_cli import backfill_cashflow
from ashare_lab.data.cninfo_industry_cli import audit_cninfo_industry_bridge
from ashare_lab.data.config import DataSettings
from ashare_lab.data.corporate_action_pipeline import persist_dividend_results
from ashare_lab.data.corporate_action_progress import (
    load_completed_dividend_dates as _completed_dividend_dates,
)
from ashare_lab.data.execution import execute_queries
from ashare_lab.data.financial_cli import backfill_income, sync_income
from ashare_lab.data.financial_indicator_cli import backfill_financial_indicators
from ashare_lab.data.historical_industry_cli import audit_historical_industry_archives
from ashare_lab.data.industry_cli import sync_industries
from ashare_lab.data.mongo_store import MongoRawStore
from ashare_lab.data.nightly import nightly_maintenance
from ashare_lab.data.queries import (
    calendar_query,
    daily_queries,
    dividend_announcement_queries,
    name_history_queries,
    security_master_queries,
)
from ashare_lab.data.rematerialization_cli import rematerialize_lineage
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.universe_pipeline import persist_universe_results

_SCHEMA_PATH = Path("schemas/tushare_p0_v1.json")
_UNIVERSE_SCHEMA_PATH = Path("schemas/tushare_universe_v1.json")
_CORPORATE_ACTION_SCHEMA_PATH = Path("schemas/tushare_corporate_actions_v1.json")
app = typer.Typer(no_args_is_help=True, help="Governed Tushare ingestion for ashare_quant.")
_CONSOLE = Console()
_SHANGHAI = ZoneInfo("Asia/Shanghai")
app.command("sync-income")(sync_income)
app.command("backfill-income")(backfill_income)
app.command("backfill-balance-sheet")(backfill_balance_sheet)
app.command("backfill-cashflow")(backfill_cashflow)
app.command("backfill-financial-indicators")(backfill_financial_indicators)
app.command("sync-benchmark-master")(sync_benchmark_master)
app.command("backfill-benchmark-daily")(backfill_benchmark_daily)
app.command("backfill-benchmark-weights")(backfill_benchmark_weights)
app.command("sync-industries")(sync_industries)
app.command("audit-industry-archives")(audit_historical_industry_archives)
app.command("audit-capco-industry-archives")(audit_capco_industry_archives)
app.command("audit-cninfo-industry-bridge")(audit_cninfo_industry_bridge)
app.command("nightly-maintenance")(nightly_maintenance)
app.command("rematerialize-lineage")(rematerialize_lineage)


@app.command("init-db")
def initialize_database() -> None:
    """Create or tighten the isolated MongoDB collections and indexes."""
    settings = DataSettings()
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    with MongoClient[BsonDocument](settings.mongodb_uri, serverSelectionTimeoutMS=8_000) as client:
        names = MongoRawStore(client, settings.mongodb_database).initialize(registry)
    _CONSOLE.print(
        f"Initialized [bold]{settings.mongodb_database}[/bold]: {len(names)} collections"
    )


@app.command("daily")
def sync_daily(
    trade_date: Annotated[str, typer.Option(help="Trading date in YYYYMMDD format.")],
) -> None:
    """Append all five daily endpoint snapshots for one trading date."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    execute_queries(registry, daily_queries(registry, trade_date))


@app.command("daily-latest")
def sync_daily_latest() -> None:
    """Sync today's market endpoints only when the exchange calendar is open."""
    trade_date = _current_trade_date()
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    calendar = execute_queries(registry, (calendar_query(registry, trade_date, trade_date),))
    if trade_date not in _open_dates(calendar[0]):
        _CONSOLE.print(f"{trade_date}: exchange closed; no daily market requests")
        return
    execute_queries(registry, daily_queries(registry, trade_date))


@app.command("daily-maintenance")
def daily_maintenance() -> None:
    """Sync today's market data and recheck recent dividend announcements."""
    sync_daily_latest()
    end_date = _current_trade_date()
    end = datetime.strptime(end_date, "%Y%m%d").replace(tzinfo=_SHANGHAI)
    start_date = (end - timedelta(days=7)).strftime("%Y%m%d")
    sync_dividends(start_date, end_date, max_days=8)


@app.command("backfill-market")
def backfill_market(
    start_date: Annotated[str, typer.Option(help="Inclusive start in YYYYMMDD format.")],
    end_date: Annotated[str, typer.Option(help="Inclusive end in YYYYMMDD format.")],
    max_days: Annotated[int, typer.Option(min=1, max=60)] = 20,
    continue_on_error: Annotated[  # noqa: FBT002
        bool,
        typer.Option(help="Continue later dates after a failed date."),
    ] = False,
) -> None:
    """Backfill a bounded, resumable batch of open trading dates."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    calendar = execute_queries(registry, (calendar_query(registry, start_date, end_date),))
    open_dates = _open_dates(calendar[0])
    completed_dates = _completed_market_dates(registry, start_date, end_date)
    pending_dates = tuple(date for date in open_dates if date not in completed_dates)[:max_days]
    succeeded: list[str] = []
    failed: list[str] = []
    for trade_date in pending_dates:
        try:
            execute_queries(registry, daily_queries(registry, trade_date))
        except Exception as error:  # noqa: BLE001
            failed.append(trade_date)
            _CONSOLE.print(f"{trade_date}: failed error={type(error).__name__}")
            if not continue_on_error:
                break
        else:
            succeeded.append(trade_date)
    skipped = len(set(open_dates) & completed_dates)
    remaining = len(pending_dates) - len(succeeded)
    _CONSOLE.print(
        f"Backfill completed={len(succeeded)} skipped={skipped} "
        f"failed={len(failed)} remaining={remaining}"
    )
    if failed:
        raise typer.Exit(code=1)


@app.command("pilot")
def sync_pilot(
    trade_date: Annotated[str, typer.Option(help="Pilot trading date in YYYYMMDD format.")],
    calendar_start: Annotated[str, typer.Option(help="Calendar start in YYYYMMDD format.")],
    calendar_end: Annotated[str, typer.Option(help="Calendar end in YYYYMMDD format.")],
) -> None:
    """Run the calendar, complete universe, and one-day market pilot."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    queries = (
        calendar_query(registry, calendar_start, calendar_end),
        *security_master_queries(registry),
        *daily_queries(registry, trade_date),
    )
    execute_queries(registry, queries)


@app.command("sync-universe")
def sync_universe(
    start_date: Annotated[str, typer.Option(help="Name history start in YYYYMMDD format.")],
    end_date: Annotated[str, typer.Option(help="Name history end in YYYYMMDD format.")],
) -> None:
    """Sync complete lifecycle sources and materialize PIT security events."""
    registry = SchemaRegistry.load(_UNIVERSE_SCHEMA_PATH)
    queries = (
        *security_master_queries(registry),
        *name_history_queries(registry, start_date, end_date),
    )
    results = execute_queries(registry, queries)
    persist_universe_results(registry, results)


@app.command("sync-dividends")
def sync_dividends(
    start_date: Annotated[str, typer.Option(help="First announcement date in YYYYMMDD.")],
    end_date: Annotated[str, typer.Option(help="Last announcement date in YYYYMMDD.")],
    max_days: Annotated[int, typer.Option(min=1, max=366)] = 31,
) -> None:
    """Sync a bounded dividend announcement range through PIT projection."""
    registry = SchemaRegistry.load(_CORPORATE_ACTION_SCHEMA_PATH)
    completed = _completed_dividend_dates(registry, start_date, end_date)
    queries = tuple(
        query
        for query in dividend_announcement_queries(registry, start_date, end_date)
        if query.params[0].value not in completed
    )[:max_days]
    for query in queries:
        results = execute_queries(registry, (query,))
        persist_dividend_results(registry, results)


def _current_trade_date() -> str:
    return datetime.now(_SHANGHAI).strftime("%Y%m%d")


def _open_dates(calendar: SyncResult) -> tuple[str, ...]:
    dates: list[str] = []
    for row in calendar.batch.rows:
        payload = dict(row.payload)
        cal_date = payload.get("cal_date")
        is_open = payload.get("is_open")
        if isinstance(cal_date, str) and is_open == 1:
            dates.append(cal_date)
    return tuple(sorted(dates))


def _completed_market_dates(
    registry: SchemaRegistry,
    start_date: str,
    end_date: str,
) -> frozenset[str]:
    settings = DataSettings()
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        store = MongoCanonicalStore(mongo, settings.mongodb_database)
        return store.completed_market_dates(registry.manifest_id, start_date, end_date)


def run() -> None:
    """Launch the operator command group."""
    app()


if __name__ == "__main__":
    run()
