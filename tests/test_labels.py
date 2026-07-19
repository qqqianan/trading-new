from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.research.labels.calculator import (
    calculate_relative_open_return,
    resolve_label_window,
)
from ashare_lab.research.labels.models import (
    BenchmarkOpenObservation,
    LabelInputError,
    LabelTradeObservation,
    LabelWindowEvidence,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_relative_label_uses_t_plus_1_and_t_plus_21_raw_opens() -> None:
    # Given: a Friday decision, governed sessions, and four raw open observations.
    sessions = label_sessions(date(2025, 1, 3), 22)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    window = resolve_label_window(sessions, decision)
    entry = stock_observation(window.entry_date, 100.0)
    exit_observation = stock_observation(window.exit_date, 110.0)
    benchmark_entry = benchmark_observation(window.entry_date, 1_000.0)
    benchmark_exit = benchmark_observation(window.exit_date, 1_050.0)

    # When: the physically isolated label is calculated.
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(entry, exit_observation, benchmark_entry, benchmark_exit),
    )

    # Then: the target is stock simple return less benchmark simple return.
    assert window.entry_date == date(2025, 1, 6)
    assert window.exit_date == sessions[21]
    assert row.value == pytest.approx(0.05)
    assert window.entry_date is not None
    assert row.entry_time == datetime.combine(window.entry_date, datetime.min.time()).replace(
        hour=9,
        minute=30,
        tzinfo=SHANGHAI,
    )
    assert row.exit_price_source_row_sha256 == "b" * 64
    assert row.benchmark_exit_source_snapshot_id == "snapshot_benchmark"


def test_limit_up_entry_remains_on_fixed_session_and_returns_null() -> None:
    # Given: the fixed next session opens at its accepted upper limit.
    sessions = label_sessions(date(2025, 1, 3), 22)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    window = resolve_label_window(sessions, decision)
    entry = stock_observation(window.entry_date, 110.0, up_limit=110.0)

    # When: label construction evaluates tradeability without shifting dates.
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(
            entry,
            stock_observation(window.exit_date, 120.0),
            benchmark_observation(window.entry_date, 1_000.0),
            benchmark_observation(window.exit_date, 1_050.0),
        ),
    )

    # Then: the fixed window is retained and the impossible entry is explicit.
    assert row.value is None
    assert row.null_reason == "ENTRY_LIMIT_UP"
    assert row.entry_time is not None
    assert row.entry_time.date() == window.entry_date
    assert row.exit_time is not None
    assert row.exit_time.date() == window.exit_date


def test_suspended_exit_does_not_move_to_later_trading_day() -> None:
    # Given: the exact t+21 exit session is suspended.
    sessions = label_sessions(date(2025, 1, 3), 24)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    window = resolve_label_window(sessions, decision)
    suspended = stock_observation(window.exit_date, None, suspended=True)

    # When: the target checks the fixed exit evidence.
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(
            stock_observation(window.entry_date, 100.0),
            suspended,
            benchmark_observation(window.entry_date, 1_000.0),
            benchmark_observation(window.exit_date, 1_050.0),
        ),
    )

    # Then: no later open is substituted for the unavailable exit.
    assert row.value is None
    assert row.null_reason == "EXIT_SUSPENDED"
    assert row.exit_time is not None
    assert row.exit_time.date() == sessions[21]


def test_incomplete_future_calendar_preserves_key_with_no_exit_session() -> None:
    # Given: fewer than 21 future governed sessions exist at the data cutoff.
    sessions = label_sessions(date(2025, 1, 3), 10)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)

    # When: the label window and row are constructed at the cutoff.
    window = resolve_label_window(sessions, decision)
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(None, None, None, None),
    )

    # Then: the universe key remains, but no future return is invented.
    assert window.entry_date == date(2025, 1, 6)
    assert window.exit_date is None
    assert row.value is None
    assert row.available_at is None
    assert row.null_reason == "NO_EXIT_SESSION"


def test_label_window_rejects_duplicate_governed_sessions() -> None:
    # Given: a calendar contains one duplicated trading session.
    sessions = label_sessions(date(2025, 1, 3), 22)
    duplicated = (*sessions[:2], sessions[1], *sessions[2:])
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)

    # When / Then: ambiguous trading-day offsets fail closed.
    with pytest.raises(LabelInputError, match="unique and strictly increasing"):
        resolve_label_window(duplicated, decision)


def test_missing_entry_limit_evidence_is_not_treated_as_tradeable() -> None:
    # Given: the fixed entry has a raw open but no accepted limit row.
    sessions = label_sessions(date(2025, 1, 3), 22)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    window = resolve_label_window(sessions, decision)
    entry = stock_observation(window.entry_date, 100.0)
    assert entry is not None
    incomplete = replace(entry, up_limit=None, down_limit=None)

    # When: the target evaluates the fixed future evidence.
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(
            incomplete,
            stock_observation(window.exit_date, 110.0),
            benchmark_observation(window.entry_date, 1_000.0),
            benchmark_observation(window.exit_date, 1_050.0),
        ),
    )

    # Then: missing execution evidence remains an explicit null.
    assert row.null_reason == "MISSING_ENTRY_LIMIT"


def test_limit_down_exit_is_not_shifted_to_a_later_open() -> None:
    # Given: the stock opens at its lower limit on the exact t+21 session.
    sessions = label_sessions(date(2025, 1, 3), 22)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    window = resolve_label_window(sessions, decision)
    exit_observation = stock_observation(window.exit_date, 80.0)

    # When: the fixed-window target checks exit feasibility.
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(
            stock_observation(window.entry_date, 100.0),
            exit_observation,
            benchmark_observation(window.entry_date, 1_000.0),
            benchmark_observation(window.exit_date, 1_050.0),
        ),
    )

    # Then: the target is null rather than using a favorable later session.
    assert row.null_reason == "EXIT_LIMIT_DOWN"


def test_missing_benchmark_open_blocks_relative_return() -> None:
    # Given: both stock prices exist but the benchmark entry row is absent.
    sessions = label_sessions(date(2025, 1, 3), 22)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    window = resolve_label_window(sessions, decision)

    # When: relative-return construction reaches benchmark evidence.
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(
            stock_observation(window.entry_date, 100.0),
            stock_observation(window.exit_date, 110.0),
            None,
            benchmark_observation(window.exit_date, 1_050.0),
        ),
    )

    # Then: no absolute stock return is silently substituted.
    assert row.null_reason == "MISSING_BENCHMARK_ENTRY_BAR"


def label_sessions(start: date, count: int) -> tuple[date, ...]:
    sessions: list[date] = []
    current = start
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def stock_observation(
    trading_date: date | None,
    price: float | None,
    *,
    up_limit: float = 120.0,
    suspended: bool = False,
) -> LabelTradeObservation | None:
    if trading_date is None:
        return None
    at = datetime(trading_date.year, trading_date.month, trading_date.day, 18, tzinfo=SHANGHAI)
    return LabelTradeObservation(
        symbol="000001.SZ",
        trading_date=trading_date,
        open_price=price,
        up_limit=None if suspended else up_limit,
        down_limit=None if suspended else 80.0,
        is_suspended=suspended,
        available_at=at,
        price_source_snapshot_id=None if price is None else "snapshot_price",
        price_source_row_sha256=None if price is None else "b" * 64,
        constraint_source_snapshot_id="snapshot_constraint",
        constraint_source_row_sha256="c" * 64,
    )


def benchmark_observation(
    trading_date: date | None,
    price: float,
) -> BenchmarkOpenObservation | None:
    if trading_date is None:
        return None
    at = datetime(trading_date.year, trading_date.month, trading_date.day, 18, tzinfo=SHANGHAI)
    return BenchmarkOpenObservation(
        symbol="000905.SH",
        trading_date=trading_date,
        open_price=price,
        available_at=at,
        source_snapshot_id="snapshot_benchmark",
        source_row_sha256="d" * 64,
    )
