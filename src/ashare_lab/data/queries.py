"""Deterministic query builders for registered P0 sync jobs."""

from datetime import date, timedelta

from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import QueryParam, TushareQuery


def daily_queries(registry: SchemaRegistry, trade_date: str) -> tuple[TushareQuery, ...]:
    """Build the five end-of-day requests for one explicit trading date."""
    endpoints = ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d")
    return tuple(
        TushareQuery(
            endpoint=name,
            params=(QueryParam(name="trade_date", value=trade_date),),
            fields=registry.endpoint(name).field_names,
        )
        for name in endpoints
    )


def security_master_queries(registry: SchemaRegistry) -> tuple[TushareQuery, ...]:
    """Build separate current, paused, and delisted universe requests."""
    schema = registry.endpoint("stock_basic")
    return tuple(
        TushareQuery(
            endpoint="stock_basic",
            params=(
                QueryParam(name="exchange", value=""),
                QueryParam(name="list_status", value=status),
            ),
            fields=schema.field_names,
        )
        for status in ("L", "P", "D")
    )


def name_history_queries(
    registry: SchemaRegistry,
    start_date: str,
    end_date: str,
) -> tuple[TushareQuery, ...]:
    """Split an inclusive name-history interval into bounded calendar years."""
    schema = registry.endpoint("namechange")
    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    return tuple(
        TushareQuery(
            endpoint="namechange",
            params=(
                QueryParam(
                    name="start_date",
                    value=start_date if year == start_year else f"{year}0101",
                ),
                QueryParam(
                    name="end_date",
                    value=end_date if year == end_year else f"{year}1231",
                ),
            ),
            fields=schema.field_names,
        )
        for year in range(start_year, end_year + 1)
    )


def dividend_announcement_queries(
    registry: SchemaRegistry,
    start_date: str,
    end_date: str,
) -> tuple[TushareQuery, ...]:
    """Build one bounded dividend request for every announcement calendar date."""
    schema = registry.endpoint("dividend")
    first = _parse_date(start_date)
    last = _parse_date(end_date)
    count = (last - first).days + 1
    if count < 1:
        return ()
    return tuple(
        TushareQuery(
            endpoint="dividend",
            params=(
                QueryParam(
                    name="ann_date", value=(first + timedelta(days=offset)).strftime("%Y%m%d")
                ),
            ),
            fields=schema.field_names,
        )
        for offset in range(count)
    )


def income_period_queries(
    registry: SchemaRegistry,
    periods: tuple[str, ...],
) -> tuple[TushareQuery, ...]:
    """Build full-market income requests partitioned by closed report period."""
    schema = registry.endpoint("income_vip")
    return tuple(
        TushareQuery(
            endpoint="income_vip",
            params=(QueryParam(name="period", value=period),),
            fields=schema.field_names,
        )
        for period in periods
    )


def income_security_queries(
    registry: SchemaRegistry,
    ts_codes: tuple[str, ...],
    start_date: str,
    end_date: str,
) -> tuple[TushareQuery, ...]:
    """Build one bounded standard income request for every lifecycle code."""
    schema = registry.endpoint("income")
    return tuple(
        TushareQuery(
            endpoint="income",
            params=(
                QueryParam(name="ts_code", value=ts_code),
                QueryParam(name="start_date", value=start_date),
                QueryParam(name="end_date", value=end_date),
            ),
            fields=schema.field_names,
        )
        for ts_code in ts_codes
    )


def balance_sheet_security_queries(
    registry: SchemaRegistry,
    ts_codes: tuple[str, ...],
    start_date: str,
    end_date: str,
) -> tuple[TushareQuery, ...]:
    """Build one bounded standard balance-sheet request per lifecycle code."""
    schema = registry.endpoint("balancesheet")
    return tuple(
        TushareQuery(
            endpoint="balancesheet",
            params=(
                QueryParam(name="ts_code", value=ts_code),
                QueryParam(name="start_date", value=start_date),
                QueryParam(name="end_date", value=end_date),
            ),
            fields=schema.field_names,
        )
        for ts_code in ts_codes
    )


def cashflow_security_queries(
    registry: SchemaRegistry,
    ts_codes: tuple[str, ...],
    start_date: str,
    end_date: str,
) -> tuple[TushareQuery, ...]:
    """Build one bounded standard cash-flow request per lifecycle code."""
    schema = registry.endpoint("cashflow")
    return tuple(
        TushareQuery(
            endpoint="cashflow",
            params=(
                QueryParam(name="ts_code", value=ts_code),
                QueryParam(name="start_date", value=start_date),
                QueryParam(name="end_date", value=end_date),
            ),
            fields=schema.field_names,
        )
        for ts_code in ts_codes
    )


def financial_indicator_security_queries(
    registry: SchemaRegistry, ts_codes: tuple[str, ...], start_date: str, end_date: str
) -> tuple[TushareQuery, ...]:
    """Build one bounded financial-indicator request per lifecycle code."""
    schema = registry.endpoint("fina_indicator")
    return tuple(
        TushareQuery(
            endpoint="fina_indicator",
            params=(
                QueryParam("ts_code", code),
                QueryParam("start_date", start_date),
                QueryParam("end_date", end_date),
            ),
            fields=schema.field_names,
        )
        for code in ts_codes
    )


def _parse_date(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def calendar_query(registry: SchemaRegistry, start_date: str, end_date: str) -> TushareQuery:
    """Build one Shanghai exchange calendar request for a closed date interval."""
    return TushareQuery(
        endpoint="trade_cal",
        params=(
            QueryParam(name="exchange", value="SSE"),
            QueryParam(name="start_date", value=start_date),
            QueryParam(name="end_date", value=end_date),
        ),
        fields=registry.endpoint("trade_cal").field_names,
    )
