"""Governed nightly market, announcement, PIT, and reference-data maintenance."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.benchmark_cli import (
    backfill_benchmark_daily,
    backfill_benchmark_weights,
    sync_benchmark_master,
)
from ashare_lab.data.corporate_action_pipeline import persist_dividend_results
from ashare_lab.data.corporate_action_progress import load_completed_dividend_dates
from ashare_lab.data.execution import execute_queries
from ashare_lab.data.industry_cli import sync_industries
from ashare_lab.data.nightly_financial import sync_financial_stage
from ashare_lab.data.nightly_schedule import NightlyPlan, NightlyStage, build_nightly_plan
from ashare_lab.data.queries import (
    calendar_query,
    daily_queries,
    dividend_announcement_queries,
    name_history_queries,
    security_master_queries,
)
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.universe_pipeline import persist_universe_results

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def nightly_maintenance() -> None:
    """Execute tonight's deterministic incremental maintenance plan."""
    run_nightly_plan(build_nightly_plan(datetime.now(_SHANGHAI).date()))


def run_nightly_plan(plan: NightlyPlan) -> None:
    """Execute ordered stages, stopping on the first failed governed boundary."""
    market_open = False
    for stage in plan.stages:
        match stage:
            case NightlyStage.MARKET:
                market_open = _sync_market(plan.run_date)
            case NightlyStage.BENCHMARK_DAILY:
                if market_open:
                    value = _format(plan.run_date)
                    backfill_benchmark_daily(value, value)
            case NightlyStage.DIVIDENDS:
                _sync_dividends(plan.run_date)
            case (
                NightlyStage.INCOME
                | NightlyStage.BALANCE_SHEET
                | NightlyStage.CASHFLOW
                | NightlyStage.FINANCIAL_INDICATORS
            ):
                start = _format(plan.run_date - timedelta(days=13))
                sync_financial_stage(stage, start, _format(plan.run_date))
            case NightlyStage.UNIVERSE:
                _sync_universe(plan.run_date)
            case NightlyStage.REFERENCE_DATA:
                _sync_reference_data(plan.run_date)


def _sync_market(run_date: date) -> bool:
    registry = SchemaRegistry.load(Path("schemas/tushare_p0_v1.json"))
    value = _format(run_date)
    calendar = execute_queries(registry, (calendar_query(registry, value, value),))[0]
    is_open = any(
        dict(row.payload).get("cal_date") == value and dict(row.payload).get("is_open") == 1
        for row in calendar.batch.rows
    )
    if is_open:
        execute_queries(registry, daily_queries(registry, value))
    return is_open


def _sync_dividends(run_date: date) -> None:
    registry = SchemaRegistry.load(Path("schemas/tushare_corporate_actions_v1.json"))
    start = _format(run_date - timedelta(days=7))
    end = _format(run_date)
    completed = load_completed_dividend_dates(registry, start, end)
    for query in dividend_announcement_queries(registry, start, end):
        if query.params[0].value not in completed:
            persist_dividend_results(registry, execute_queries(registry, (query,)))


def _sync_universe(run_date: date) -> None:
    registry = SchemaRegistry.load(Path("schemas/tushare_universe_v1.json"))
    start = _format(run_date - timedelta(days=370))
    end = _format(run_date)
    queries = (*security_master_queries(registry), *name_history_queries(registry, start, end))
    persist_universe_results(registry, execute_queries(registry, queries))


def _sync_reference_data(run_date: date) -> None:
    end = _format(run_date)
    start = _format(_month_start_before(run_date, months=2))
    sync_benchmark_master()
    backfill_benchmark_weights(start, end, max_requests=15)
    sync_industries(max_requests=31)


def _month_start_before(value: date, *, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _format(value: date) -> str:
    return value.strftime("%Y%m%d")
