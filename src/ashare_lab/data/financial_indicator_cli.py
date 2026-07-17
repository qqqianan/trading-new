"""Financial-indicator command registered by the governed data CLI."""

from pathlib import Path
from typing import Annotated

import typer

from ashare_lab.data.execution import execute_queries
from ashare_lab.data.financial_indicator_pipeline import persist_financial_indicator_results
from ashare_lab.data.financial_indicator_progress import (
    load_completed_indicator_codes,
    load_indicator_security_codes,
)
from ashare_lab.data.queries import financial_indicator_security_queries
from ashare_lab.data.schema_registry import SchemaRegistry

_SCHEMA_PATH = Path("schemas/tushare_financial_indicator_v1.json")


def backfill_financial_indicators(
    start_date: Annotated[str, typer.Option(help="First announcement date in YYYYMMDD.")],
    end_date: Annotated[str, typer.Option(help="Last announcement date in YYYYMMDD.")],
    max_securities: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    """Backfill a bounded, evidence-resumable lifecycle security set."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    complete = load_completed_indicator_codes(registry, start_date, end_date)
    pending = tuple(code for code in load_indicator_security_codes() if code not in complete)
    for query in financial_indicator_security_queries(
        registry, pending[:max_securities], start_date, end_date
    ):
        results = execute_queries(registry, (query,))
        persist_financial_indicator_results(registry, results)
