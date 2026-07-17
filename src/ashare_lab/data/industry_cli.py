"""Industry taxonomy and observed membership commands."""

from pathlib import Path
from typing import Annotated

import typer

from ashare_lab.data.execution import execute_queries
from ashare_lab.data.industry_pipeline import persist_industry_results
from ashare_lab.data.industry_queries import (
    industry_master_query,
    industry_member_queries,
    level_one_industry_codes,
)
from ashare_lab.data.schema_registry import SchemaRegistry

_SCHEMA_PATH = Path("schemas/tushare_industry_v1.json")


def sync_industries(
    max_requests: Annotated[int, typer.Option(min=1, max=31)] = 31,
) -> None:
    """Sync SW2021 taxonomy and exact L1 membership observations."""
    registry = SchemaRegistry.load(_SCHEMA_PATH)
    master = execute_queries(registry, (industry_master_query(registry),))[0]
    queries = industry_member_queries(
        registry,
        level_one_industry_codes(master.batch),
    )[:max_requests]
    for query in queries:
        results = execute_queries(registry, (query,))
        persist_industry_results(registry, results)
