"""Benchmark commands registered by the governed data CLI."""

from pathlib import Path
from typing import Annotated

import typer

from ashare_lab.data.benchmark_pipeline import persist_benchmark_weight_results
from ashare_lab.data.benchmark_queries import (
    benchmark_daily_queries,
    benchmark_master_queries,
    benchmark_weight_queries,
)
from ashare_lab.data.execution import execute_queries
from ashare_lab.data.schema_registry import SchemaRegistry

_SCHEMA_PATH = Path("schemas/tushare_benchmarks_v1.json")


def sync_benchmark_master() -> None:
    """Sync current observed index-master snapshots through canonical governance."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    execute_queries(registry, benchmark_master_queries(registry))


def backfill_benchmark_daily(
    start_date: Annotated[str, typer.Option(help="First trade date in YYYYMMDD.")],
    end_date: Annotated[str, typer.Option(help="Last trade date in YYYYMMDD.")],
) -> None:
    """Backfill all six benchmark daily series through canonical governance."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    execute_queries(registry, benchmark_daily_queries(registry, start_date, end_date))


def backfill_benchmark_weights(
    start_date: Annotated[str, typer.Option(help="First month date in YYYYMMDD.")],
    end_date: Annotated[str, typer.Option(help="Last month date in YYYYMMDD.")],
    max_requests: Annotated[int, typer.Option(min=1, max=500)] = 100,
) -> None:
    """Backfill bounded monthly weight requests through PIT projection."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    for query in benchmark_weight_queries(registry, start_date, end_date)[:max_requests]:
        results = execute_queries(registry, (query,))
        persist_benchmark_weight_results(registry, results)
