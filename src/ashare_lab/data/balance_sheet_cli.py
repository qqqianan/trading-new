"""Balance-sheet command registered by the governed data CLI."""

from pathlib import Path
from typing import Annotated

import typer

from ashare_lab.data.balance_sheet_pipeline import persist_balance_sheet_results
from ashare_lab.data.balance_sheet_progress import (
    load_balance_sheet_security_codes,
    load_completed_balance_sheet_codes,
)
from ashare_lab.data.execution import execute_queries
from ashare_lab.data.queries import balance_sheet_security_queries
from ashare_lab.data.schema_registry import SchemaRegistry

_SCHEMA_PATH = Path("schemas/tushare_balance_sheet_v1.json")


def backfill_balance_sheet(
    start_date: Annotated[str, typer.Option(help="First announcement date in YYYYMMDD.")],
    end_date: Annotated[str, typer.Option(help="Last announcement date in YYYYMMDD.")],
    max_securities: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    """Backfill a bounded, evidence-resumable lifecycle security set."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    completed = load_completed_balance_sheet_codes(registry, start_date, end_date)
    pending = tuple(code for code in load_balance_sheet_security_codes() if code not in completed)
    queries = balance_sheet_security_queries(
        registry,
        pending[:max_securities],
        start_date,
        end_date,
    )
    for query in queries:
        results = execute_queries(registry, (query,))
        persist_balance_sheet_results(registry, results)
