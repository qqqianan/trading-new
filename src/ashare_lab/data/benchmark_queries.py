"""Deterministic Tushare queries for the committed benchmark universe."""

from calendar import monthrange
from datetime import date
from typing import Final

from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import QueryParam, TushareQuery

BENCHMARK_CODES: Final[tuple[str, ...]] = (
    "000001.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "399001.SZ",
    "899050.BJ",
)
WEIGHTED_BENCHMARK_CODES: Final[tuple[str, ...]] = BENCHMARK_CODES[1:]


def benchmark_master_queries(registry: SchemaRegistry) -> tuple[TushareQuery, ...]:
    """Build one exact index-master request per benchmark to avoid provider caps."""
    fields = registry.endpoint("index_basic").field_names
    return tuple(
        TushareQuery("index_basic", (QueryParam("ts_code", code),), fields)
        for code in BENCHMARK_CODES
    )


def benchmark_daily_queries(
    registry: SchemaRegistry, start_date: str, end_date: str
) -> tuple[TushareQuery, ...]:
    """Build one bounded daily-bar request per benchmark."""
    fields = registry.endpoint("index_daily").field_names
    return tuple(
        TushareQuery(
            "index_daily",
            (
                QueryParam("ts_code", code),
                QueryParam("start_date", start_date),
                QueryParam("end_date", end_date),
            ),
            fields,
        )
        for code in BENCHMARK_CODES
    )


def benchmark_weight_queries(
    registry: SchemaRegistry, start_date: str, end_date: str
) -> tuple[TushareQuery, ...]:
    """Build one bounded calendar-month weight request per benchmark."""
    fields = registry.endpoint("index_weight").field_names
    return tuple(
        TushareQuery(
            "index_weight",
            (
                QueryParam("index_code", code),
                QueryParam("start_date", start),
                QueryParam("end_date", end),
            ),
            fields,
        )
        for code in WEIGHTED_BENCHMARK_CODES
        for start, end in _month_ranges(start_date, end_date)
    )


def _month_ranges(start_date: str, end_date: str) -> tuple[tuple[str, str], ...]:
    first = date.fromisoformat(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}")
    last = date.fromisoformat(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}")
    ranges: list[tuple[str, str]] = []
    cursor = first.replace(day=1)
    while cursor <= last:
        month_end = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
        following = date.fromordinal(month_end.toordinal() + 1)
        ranges.append(
            (max(first, cursor).strftime("%Y%m%d"), min(last, month_end).strftime("%Y%m%d"))
        )
        cursor = following
    return tuple(ranges)
