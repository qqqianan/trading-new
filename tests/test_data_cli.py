from collections.abc import Callable

import pytest
import typer

from ashare_lab.data import cli as data_cli
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.tushare_client import TushareQuery


class ProviderUnavailableError(RuntimeError):
    """Represent a provider outage in CLI orchestration tests."""


def test_daily_command_delegates_only_registered_daily_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a recorder replacing the external network and database boundary.
    captured: list[tuple[str, ...]] = []

    def record(registry: SchemaRegistry, queries: tuple[TushareQuery, ...]) -> None:
        assert registry.database == "ashare_quant"
        captured.append(tuple(query.endpoint for query in queries))

    _replace_executor(monkeypatch, record)

    # When: the operator runs one daily job.
    data_cli.sync_daily("20260710")

    # Then: exactly the five approved daily endpoints are delegated.
    assert captured == [("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d")]


def test_daily_maintenance_syncs_market_then_recent_dividend_announcements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: recorders replacing the two governed maintenance stages.
    stages: list[str] = []
    dividend_ranges: list[tuple[str, str, int]] = []
    monkeypatch.setattr(data_cli, "sync_daily_latest", lambda: stages.append("market"))
    monkeypatch.setattr(data_cli, "_current_trade_date", lambda: "20260716", raising=False)
    monkeypatch.setattr(
        data_cli,
        "sync_dividends",
        lambda start, end, max_days: dividend_ranges.append((start, end, max_days)),
    )

    # When: the scheduled maintenance entry point runs.
    data_cli.daily_maintenance()

    # Then: market data runs first and dividend announcements receive a seven-day lookback.
    assert stages == ["market"]
    assert dividend_ranges == [("20260709", "20260716", 8)]


def test_pilot_command_includes_calendar_and_all_universe_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a recorder replacing external side effects.
    captured: list[tuple[str, ...]] = []

    def record(registry: SchemaRegistry, queries: tuple[TushareQuery, ...]) -> None:
        assert registry.database == "ashare_quant"
        captured.append(tuple(query.endpoint for query in queries))

    _replace_executor(monkeypatch, record)

    # When: the pilot command is built.
    data_cli.sync_pilot("20260710", "20260701", "20260731")

    # Then: it includes calendar, L/P/D universe calls, and daily snapshots.
    assert captured[0][:4] == ("trade_cal", "stock_basic", "stock_basic", "stock_basic")
    assert len(captured[0]) == 9


def test_universe_sync_includes_all_lifecycle_states_and_yearly_name_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: side-effect recorders for provider queries and event persistence.
    captured: list[tuple[str, ...]] = []
    persisted: list[int] = []

    def record(
        registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[None, ...]:
        assert registry.endpoint_names == ("namechange", "stock_basic")
        captured.append(tuple(query.endpoint for query in queries))
        return ()

    monkeypatch.setattr(data_cli, "execute_queries", record)
    monkeypatch.setattr(
        data_cli,
        "persist_universe_results",
        lambda _registry, results: persisted.append(len(results)),
        raising=False,
    )

    # When: a three-year universe history is synchronized.
    data_cli.sync_universe("20200101", "20221231")

    # Then: L/P/D master snapshots and one bounded name request per year are governed.
    assert captured == [
        ("stock_basic", "stock_basic", "stock_basic", "namechange", "namechange", "namechange")
    ]
    assert persisted == [0]


def test_dividend_sync_skips_only_dates_with_complete_pit_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the first date already has accepted Raw, canonical, and PIT batch evidence.
    attempted: list[str] = []
    persisted: list[int] = []

    def record(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[None, ...]:
        attempted.append(queries[0].params[0].value)
        return ()

    monkeypatch.setattr(data_cli, "execute_queries", record)
    monkeypatch.setattr(
        data_cli,
        "_completed_dividend_dates",
        lambda _registry, _start, _end: frozenset({"20260710"}),
        raising=False,
    )
    monkeypatch.setattr(
        data_cli,
        "persist_dividend_results",
        lambda _registry, results: persisted.append(len(results)),
        raising=False,
    )

    # When: a bounded two-day dividend batch resumes.
    data_cli.sync_dividends("20260710", "20260713", max_days=2)

    # Then: it advances to the next two dates and persists each PIT projection.
    assert attempted == ["20260711", "20260712"]
    assert persisted == [0, 0]


def test_backfill_skips_completed_dates_before_applying_batch_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the first open date already has complete current-schema evidence.
    captured: list[tuple[str, ...]] = []

    def record(
        registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[None, ...]:
        assert registry.database == "ashare_quant"
        captured.append(tuple(_trade_date(query) for query in queries))
        return (None,)

    _replace_executor(monkeypatch, record)
    monkeypatch.setattr(
        data_cli,
        "_open_dates",
        lambda _calendar: ("20260601", "20260602", "20260603"),
    )
    monkeypatch.setattr(
        data_cli,
        "_completed_market_dates",
        lambda _registry, _start, _end: frozenset({"20260601"}),
        raising=False,
    )

    # When: a bounded two-day backfill resumes.
    data_cli.backfill_market("20260601", "20260603", max_days=2)

    # Then: the batch advances to the next two incomplete dates.
    assert captured[1:] == [
        ("20260602",) * 5,
        ("20260603",) * 5,
    ]


def test_backfill_stops_after_one_failed_date_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: three pending dates and a provider failure on the first date.
    attempted: list[str] = []

    def fail_first(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[None, ...]:
        if queries[0].endpoint == "trade_cal":
            return (None,)
        attempted.append(queries[0].params[0].value)
        raise ProviderUnavailableError

    _replace_executor(monkeypatch, fail_first)
    _replace_backfill_state(monkeypatch)

    # When / Then: the command exits unsuccessfully without touching later dates.
    with pytest.raises(typer.Exit):
        data_cli.backfill_market("20260601", "20260603", max_days=3)
    assert attempted == ["20260601"]


def test_backfill_can_continue_after_a_failed_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the first date fails while the next two dates are healthy.
    attempted: list[str] = []

    def fail_then_succeed(
        _registry: SchemaRegistry,
        queries: tuple[TushareQuery, ...],
    ) -> tuple[None, ...]:
        if queries[0].endpoint == "trade_cal":
            return (None,)
        trade_date = queries[0].params[0].value
        attempted.append(trade_date)
        if trade_date == "20260601":
            raise ProviderUnavailableError
        return (None,)

    _replace_executor(monkeypatch, fail_then_succeed)
    _replace_backfill_state(monkeypatch)

    # When / Then: explicit continuation attempts the whole bounded batch and exits non-zero.
    with pytest.raises(typer.Exit):
        data_cli.backfill_market(
            "20260601",
            "20260603",
            max_days=3,
            continue_on_error=True,
        )
    assert attempted == ["20260601", "20260602", "20260603"]


def _replace_executor(
    monkeypatch: pytest.MonkeyPatch,
    replacement: Callable[[SchemaRegistry, tuple[TushareQuery, ...]], None],
) -> None:
    monkeypatch.setattr(data_cli, "execute_queries", replacement)


def _trade_date(query: TushareQuery) -> str:
    if query.endpoint == "trade_cal":
        return query.endpoint
    return query.params[0].value


def _replace_backfill_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        data_cli,
        "_open_dates",
        lambda _calendar: ("20260601", "20260602", "20260603"),
    )
    monkeypatch.setattr(
        data_cli,
        "_completed_market_dates",
        lambda _registry, _start, _end: frozenset(),
    )
