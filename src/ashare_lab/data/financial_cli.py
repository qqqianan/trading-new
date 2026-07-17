"""Financial-data command functions registered by the root data CLI."""

from pathlib import Path
from typing import Annotated

import typer

from ashare_lab.data.execution import execute_queries
from ashare_lab.data.financial_pipeline import persist_income_results
from ashare_lab.data.financial_progress import (
    load_completed_income_codes,
    load_income_security_codes,
)
from ashare_lab.data.queries import income_period_queries, income_security_queries
from ashare_lab.data.schema_registry import SchemaRegistry

_SCHEMA_PATH = Path("schemas/tushare_financials_v1.json")


def sync_income(
    period: Annotated[str, typer.Option(help="Closed report period in YYYYMMDD format.")],
) -> None:
    """Sync one full-market income report period through PIT projection."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    results = execute_queries(registry, income_period_queries(registry, (period,)))
    persist_income_results(registry, results)


def backfill_income(
    start_date: Annotated[str, typer.Option(help="First announcement date in YYYYMMDD.")],
    end_date: Annotated[str, typer.Option(help="Last announcement date in YYYYMMDD.")],
    max_securities: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    """Backfill a bounded, evidence-resumable set of lifecycle securities."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    completed = load_completed_income_codes(registry, start_date, end_date)
    pending = tuple(code for code in load_income_security_codes() if code not in completed)
    queries = income_security_queries(
        registry,
        pending[:max_securities],
        start_date,
        end_date,
    )
    for query in queries:
        results = execute_queries(registry, (query,))
        persist_income_results(registry, results)
