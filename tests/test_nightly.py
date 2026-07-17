from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data import nightly, nightly_financial
from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.nightly_financial import FinancialStage
from ashare_lab.data.nightly_schedule import NightlyPlan, NightlyStage
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_nightly_execution_orders_daily_and_weekly_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a Monday plan with recording governed stage boundaries.
    calls: list[str] = []

    def market(_run_date: date) -> bool:
        calls.append("market")
        return True

    def benchmark(start: str, end: str) -> None:
        calls.append(f"benchmark:{start}:{end}")

    def dividends(_run_date: date) -> None:
        calls.append("dividends")

    def financial(stage: FinancialStage, start: str, end: str) -> None:
        calls.append(f"{stage.value}:{start}:{end}")

    monkeypatch.setattr(nightly, "_sync_market", market)
    monkeypatch.setattr(nightly, "backfill_benchmark_daily", benchmark)
    monkeypatch.setattr(nightly, "_sync_dividends", dividends)
    monkeypatch.setattr(nightly, "sync_financial_stage", financial)
    plan = NightlyPlan(
        date(2026, 7, 13),
        (
            NightlyStage.MARKET,
            NightlyStage.BENCHMARK_DAILY,
            NightlyStage.DIVIDENDS,
            NightlyStage.INCOME,
        ),
    )

    # When: the plan executes.
    nightly.run_nightly_plan(plan)

    # Then: dependencies precede the bounded 14-day financial refresh.
    assert calls == [
        "market",
        "benchmark:20260713:20260713",
        "dividends",
        "income:20260630:20260713",
    ]


def test_closed_market_skips_only_benchmark_daily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a closed Sunday and recording daily announcement maintenance.
    calls: list[str] = []

    def closed(_run_date: date) -> bool:
        calls.append("market")
        return False

    def benchmark(_start: str, _end: str) -> None:
        calls.append("benchmark")

    def dividends(_run_date: date) -> None:
        calls.append("dividends")

    monkeypatch.setattr(nightly, "_sync_market", closed)
    monkeypatch.setattr(nightly, "backfill_benchmark_daily", benchmark)
    monkeypatch.setattr(nightly, "_sync_dividends", dividends)

    # When: core freshness stages execute.
    nightly.run_nightly_plan(
        NightlyPlan(
            date(2026, 7, 19),
            (
                NightlyStage.MARKET,
                NightlyStage.BENCHMARK_DAILY,
                NightlyStage.DIVIDENDS,
            ),
        )
    )

    # Then: dividends still look back while exchange-only data is skipped.
    assert calls == ["market", "dividends"]


def test_reference_stage_rechecks_two_complete_calendar_months(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a Saturday reference refresh with recording commands.
    calls: list[str] = []

    def master() -> None:
        calls.append("master")

    def weights(start: str, end: str, max_requests: int) -> None:
        calls.append(f"weights:{start}:{end}:{max_requests}")

    def industries(max_requests: int) -> None:
        calls.append(f"industries:{max_requests}")

    monkeypatch.setattr(nightly, "sync_benchmark_master", master)
    monkeypatch.setattr(nightly, "backfill_benchmark_weights", weights)
    monkeypatch.setattr(nightly, "sync_industries", industries)

    # When: reference maintenance runs.
    nightly.run_nightly_plan(NightlyPlan(date(2026, 7, 18), (NightlyStage.REFERENCE_DATA,)))

    # Then: retries cover current month plus the preceding two month starts.
    assert calls == [
        "master",
        "weights:20260501:20260718:15",
        "industries:31",
    ]


@pytest.mark.parametrize(
    ("stage", "target"),
    [
        (NightlyStage.INCOME, "_sync_income"),
        (NightlyStage.BALANCE_SHEET, "_sync_balance_sheet"),
        (NightlyStage.CASHFLOW, "_sync_cashflow"),
        (NightlyStage.FINANCIAL_INDICATORS, "_sync_indicators"),
    ],
)
def test_financial_stage_dispatch_is_closed_and_explicit(
    monkeypatch: pytest.MonkeyPatch,
    stage: FinancialStage,
    target: str,
) -> None:
    # Given: recording implementations for each permitted financial family.
    calls: list[str] = []

    def record(_start: str, _end: str) -> None:
        calls.append(target)

    monkeypatch.setattr(nightly_financial, target, record)

    # When: one weekly financial stage dispatches.
    nightly_financial.sync_financial_stage(stage, "20260630", "20260713")

    # Then: exactly the declared financial pipeline runs.
    assert calls == [target]


def test_weekly_financial_refresh_skips_complete_codes_and_checkpoints_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 151 lifecycle codes with one already carrying complete range evidence.
    batch_sizes: list[int] = []
    persisted: list[int] = []
    codes = tuple(f"{index:06d}.SZ" for index in range(151))

    def completed(_registry: SchemaRegistry, _start: str, _end: str) -> frozenset[str]:
        return frozenset({codes[0]})

    def execute(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[SyncResult, ...]:
        batch_sizes.append(len(queries))
        return ()

    def persist(_registry: SchemaRegistry, results: tuple[SyncResult, ...]) -> None:
        persisted.append(len(results))

    monkeypatch.setattr(nightly_financial, "load_income_security_codes", lambda: codes)
    monkeypatch.setattr(nightly_financial, "load_completed_income_codes", completed)
    monkeypatch.setattr(nightly_financial, "execute_queries", execute)
    monkeypatch.setattr(nightly_financial, "persist_income_results", persist)

    # When: the Monday financial range resumes.
    nightly_financial.sync_financial_stage(
        NightlyStage.INCOME,
        "20260630",
        "20260713",
    )

    # Then: only pending codes run and each completed chunk gets a PIT checkpoint.
    assert batch_sizes == [100, 50]
    assert persisted == [0, 0]


def test_market_stage_uses_calendar_before_market_and_benchmark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an open exchange calendar response and recording query execution.
    calls: list[tuple[str, ...]] = []
    calendar = _calendar_result("20260713", is_open=1)

    def execute(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[SyncResult, ...]:
        calls.append(tuple(query.endpoint for query in queries))
        return (calendar,) if queries[0].endpoint == "trade_cal" else ()

    def benchmark(start: str, end: str) -> None:
        calls.append((f"benchmark:{start}:{end}",))

    monkeypatch.setattr(nightly, "execute_queries", execute)
    monkeypatch.setattr(nightly, "backfill_benchmark_daily", benchmark)

    # When: market and benchmark stages run in order.
    nightly.run_nightly_plan(
        NightlyPlan(
            date(2026, 7, 13),
            (NightlyStage.MARKET, NightlyStage.BENCHMARK_DAILY),
        )
    )

    # Then: calendar gates both stock and benchmark requests.
    assert calls == [
        ("trade_cal",),
        ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d"),
        ("benchmark:20260713:20260713",),
    ]


def test_dividend_stage_skips_dates_with_complete_batch_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one completed date within the eight-day announcement lookback.
    attempted: list[str] = []
    persisted: list[int] = []

    def completed(_registry: SchemaRegistry, _start: str, _end: str) -> frozenset[str]:
        return frozenset({"20260710"})

    def execute(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[SyncResult, ...]:
        attempted.append(queries[0].params[0].value)
        return ()

    def persist(_registry: SchemaRegistry, results: tuple[SyncResult, ...]) -> None:
        persisted.append(len(results))

    monkeypatch.setattr(nightly, "load_completed_dividend_dates", completed)
    monkeypatch.setattr(nightly, "execute_queries", execute)
    monkeypatch.setattr(nightly, "persist_dividend_results", persist)

    # When: the nightly dividend stage executes.
    nightly.run_nightly_plan(NightlyPlan(date(2026, 7, 13), (NightlyStage.DIVIDENDS,)))

    # Then: completed evidence is respected while every other date is projected.
    assert "20260710" not in attempted
    assert attempted[0] == "20260706"
    assert attempted[-1] == "20260713"
    assert len(persisted) == 7


def test_universe_stage_refreshes_all_states_and_recent_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: recording governed universe boundaries.
    endpoints: list[tuple[str, ...]] = []
    persisted: list[int] = []

    def execute(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[SyncResult, ...]:
        endpoints.append(tuple(query.endpoint for query in queries))
        return ()

    def persist(_registry: SchemaRegistry, results: tuple[SyncResult, ...]) -> None:
        persisted.append(len(results))

    monkeypatch.setattr(nightly, "execute_queries", execute)
    monkeypatch.setattr(nightly, "persist_universe_results", persist)

    # When: Friday universe maintenance executes.
    nightly.run_nightly_plan(NightlyPlan(date(2026, 7, 17), (NightlyStage.UNIVERSE,)))

    # Then: L/P/D and bounded cross-year name history use one governed call.
    assert endpoints == [("stock_basic", "stock_basic", "stock_basic", "namechange", "namechange")]
    assert persisted == [0]


@pytest.mark.parametrize(
    ("stage", "codes_name", "complete_name"),
    [
        (
            NightlyStage.BALANCE_SHEET,
            "load_balance_sheet_security_codes",
            "load_completed_balance_sheet_codes",
        ),
        (
            NightlyStage.CASHFLOW,
            "load_cashflow_security_codes",
            "load_completed_cashflow_codes",
        ),
        (
            NightlyStage.FINANCIAL_INDICATORS,
            "load_indicator_security_codes",
            "load_completed_indicator_codes",
        ),
    ],
)
def test_completed_financial_ranges_issue_no_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
    stage: FinancialStage,
    codes_name: str,
    complete_name: str,
) -> None:
    # Given: one lifecycle code with complete Raw, canonical, PIT, and quality evidence.
    calls: list[str] = []

    def codes() -> tuple[str, ...]:
        return ("000001.SZ",)

    def completed(_registry: SchemaRegistry, _start: str, _end: str) -> frozenset[str]:
        return frozenset({"000001.SZ"})

    def execute(
        _registry: SchemaRegistry,
        _queries: tuple[TushareQuery, ...],
    ) -> tuple[SyncResult, ...]:
        calls.append("provider")
        return ()

    monkeypatch.setattr(nightly_financial, codes_name, codes)
    monkeypatch.setattr(nightly_financial, complete_name, completed)
    monkeypatch.setattr(nightly_financial, "execute_queries", execute)

    # When: the weekly range resumes.
    nightly_financial.sync_financial_stage(stage, "20260630", "20260713")

    # Then: completion evidence suppresses all provider traffic.
    assert calls == []


def test_nightly_entrypoint_uses_current_plan_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a recording plan boundary independent of the wall-clock date.
    plans: list[NightlyPlan] = []
    expected = NightlyPlan(date(2026, 7, 19), (NightlyStage.DIVIDENDS,))

    def build(_run_date: date) -> NightlyPlan:
        return expected

    def run(plan: NightlyPlan) -> None:
        plans.append(plan)

    monkeypatch.setattr(nightly, "build_nightly_plan", build)
    monkeypatch.setattr(nightly, "run_nightly_plan", run)

    # When: the installed CLI entrypoint executes.
    nightly.nightly_maintenance()

    # Then: orchestration receives exactly the plan built for tonight.
    assert plans == [expected]


def _calendar_result(trade_date: str, *, is_open: int) -> SyncResult:
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_p0_v1.json")
    schema = registry.endpoint("trade_cal")
    values = (("SSE", trade_date, is_open, "20260710"),)
    now = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        TushareQuery("trade_cal", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(now, now),
    )
    return SyncResult(
        StoredSnapshot(raw.snapshot.snapshot_id, 1, inserted=True),
        raw,
    )
