"""Bounded weekly financial refreshes with evidence-based resume."""

from pathlib import Path
from typing import Final, Literal

from ashare_lab.data.balance_sheet_pipeline import persist_balance_sheet_results
from ashare_lab.data.balance_sheet_progress import (
    load_balance_sheet_security_codes,
    load_completed_balance_sheet_codes,
)
from ashare_lab.data.cashflow_pipeline import persist_cashflow_results
from ashare_lab.data.cashflow_progress import (
    load_cashflow_security_codes,
    load_completed_cashflow_codes,
)
from ashare_lab.data.execution import execute_queries
from ashare_lab.data.financial_indicator_pipeline import persist_financial_indicator_results
from ashare_lab.data.financial_indicator_progress import (
    load_completed_indicator_codes,
    load_indicator_security_codes,
)
from ashare_lab.data.financial_pipeline import persist_income_results
from ashare_lab.data.financial_progress import (
    load_completed_income_codes,
    load_income_security_codes,
)
from ashare_lab.data.nightly_schedule import NightlyStage
from ashare_lab.data.queries import (
    balance_sheet_security_queries,
    cashflow_security_queries,
    financial_indicator_security_queries,
    income_security_queries,
)
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import TushareQuery

_CHUNK_SIZE: Final = 100
type FinancialStage = Literal[
    NightlyStage.INCOME,
    NightlyStage.BALANCE_SHEET,
    NightlyStage.CASHFLOW,
    NightlyStage.FINANCIAL_INDICATORS,
]


def sync_financial_stage(stage: FinancialStage, start_date: str, end_date: str) -> None:
    """Refresh one financial family while preserving bounded PIT checkpoints."""
    match stage:
        case NightlyStage.INCOME:
            _sync_income(start_date, end_date)
        case NightlyStage.BALANCE_SHEET:
            _sync_balance_sheet(start_date, end_date)
        case NightlyStage.CASHFLOW:
            _sync_cashflow(start_date, end_date)
        case NightlyStage.FINANCIAL_INDICATORS:
            _sync_indicators(start_date, end_date)


def _sync_income(start_date: str, end_date: str) -> None:
    registry = SchemaRegistry.load(Path("schemas/tushare_financials_v1.json"))
    completed = load_completed_income_codes(registry, start_date, end_date)
    codes = tuple(code for code in load_income_security_codes() if code not in completed)
    for queries in _chunks(income_security_queries(registry, codes, start_date, end_date)):
        persist_income_results(registry, execute_queries(registry, queries))


def _sync_balance_sheet(start_date: str, end_date: str) -> None:
    registry = SchemaRegistry.load(Path("schemas/tushare_balance_sheet_v1.json"))
    completed = load_completed_balance_sheet_codes(registry, start_date, end_date)
    codes = tuple(code for code in load_balance_sheet_security_codes() if code not in completed)
    for queries in _chunks(balance_sheet_security_queries(registry, codes, start_date, end_date)):
        persist_balance_sheet_results(registry, execute_queries(registry, queries))


def _sync_cashflow(start_date: str, end_date: str) -> None:
    registry = SchemaRegistry.load(Path("schemas/tushare_cashflow_v1.json"))
    completed = load_completed_cashflow_codes(registry, start_date, end_date)
    codes = tuple(code for code in load_cashflow_security_codes() if code not in completed)
    for queries in _chunks(cashflow_security_queries(registry, codes, start_date, end_date)):
        persist_cashflow_results(registry, execute_queries(registry, queries))


def _sync_indicators(start_date: str, end_date: str) -> None:
    registry = SchemaRegistry.load(Path("schemas/tushare_financial_indicator_v1.json"))
    completed = load_completed_indicator_codes(registry, start_date, end_date)
    codes = tuple(code for code in load_indicator_security_codes() if code not in completed)
    queries = financial_indicator_security_queries(registry, codes, start_date, end_date)
    for chunk in _chunks(queries):
        persist_financial_indicator_results(registry, execute_queries(registry, chunk))


def _chunks(queries: tuple[TushareQuery, ...]) -> tuple[tuple[TushareQuery, ...], ...]:
    return tuple(
        queries[index : index + _CHUNK_SIZE] for index in range(0, len(queries), _CHUNK_SIZE)
    )
