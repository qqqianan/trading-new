"""Cash-flow command registered by the governed data CLI."""

from pathlib import Path
from typing import Annotated

import typer

from ashare_lab.data.cashflow_pipeline import persist_cashflow_results
from ashare_lab.data.cashflow_progress import (
    load_cashflow_security_codes,
    load_completed_cashflow_codes,
)
from ashare_lab.data.execution import execute_queries
from ashare_lab.data.queries import cashflow_security_queries
from ashare_lab.data.schema_registry import SchemaRegistry

_SCHEMA_PATH = Path("schemas/tushare_cashflow_v1.json")


def backfill_cashflow(
    start_date: Annotated[str, typer.Option(help="First announcement date in YYYYMMDD.")],
    end_date: Annotated[str, typer.Option(help="Last announcement date in YYYYMMDD.")],
    max_securities: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    """Backfill a bounded, evidence-resumable lifecycle security set."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    completed = load_completed_cashflow_codes(registry, start_date, end_date)
    pending = tuple(code for code in load_cashflow_security_codes() if code not in completed)
    queries = cashflow_security_queries(registry, pending[:max_securities], start_date, end_date)
    for query in queries:
        results = execute_queries(registry, (query,))
        persist_cashflow_results(registry, results)
