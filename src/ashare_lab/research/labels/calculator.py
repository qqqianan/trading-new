"""Calendar-indexed raw-open calculation for the isolated future label."""

from datetime import date, datetime, time
from math import isfinite

from ashare_lab.research.labels.catalog import medium_horizon_label
from ashare_lab.research.labels.models import (
    BenchmarkOpenObservation,
    LabelInputError,
    LabelTradeObservation,
    LabelWindow,
    LabelWindowEvidence,
    RelativeReturnLabelRow,
)


def resolve_label_window(
    open_dates: tuple[date, ...],
    decision_time: datetime,
) -> LabelWindow:
    """Resolve fixed trading-session offsets without calendar-day arithmetic."""
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        detail = "decision_time must be timezone-aware"
        raise LabelInputError(detail)
    if tuple(sorted(set(open_dates))) != open_dates:
        detail = "open sessions must be unique and strictly increasing"
        raise LabelInputError(detail)
    try:
        decision_index = open_dates.index(decision_time.date())
    except ValueError as error:
        detail = "decision date is absent from the governed calendar"
        raise LabelInputError(detail) from error
    definition = medium_horizon_label()
    entry_index = decision_index + definition.entry_lag_trading_days
    exit_index = entry_index + definition.holding_period_trading_days
    entry = open_dates[entry_index] if entry_index < len(open_dates) else None
    exit_date = open_dates[exit_index] if exit_index < len(open_dates) else None
    return LabelWindow(entry, exit_date)


def calculate_relative_open_return(
    symbol: str,
    decision_time: datetime,
    window: LabelWindow,
    evidence: LabelWindowEvidence,
) -> RelativeReturnLabelRow:
    """Calculate raw-open excess return or preserve one stable missing reason."""
    definition = medium_horizon_label()
    reason = _null_reason(
        symbol,
        window,
        evidence,
    )
    value = _label_value(reason, evidence)
    return RelativeReturnLabelRow(
        symbol=symbol,
        decision_time=decision_time,
        entry_time=_open_time(window.entry_date, decision_time),
        exit_time=_open_time(window.exit_date, decision_time),
        label_id=definition.name,
        label_version=definition.version,
        value=value,
        available_at=_label_available_at(
            window.exit_date,
            decision_time,
            evidence,
        ),
        null_reason=reason,
        entry_price_source_snapshot_id=_price_snapshot(evidence.entry),
        entry_price_source_row_sha256=_price_row(evidence.entry),
        entry_constraint_source_snapshot_id=_constraint_snapshot(evidence.entry),
        entry_constraint_source_row_sha256=_constraint_row(evidence.entry),
        exit_price_source_snapshot_id=_price_snapshot(evidence.exit),
        exit_price_source_row_sha256=_price_row(evidence.exit),
        exit_constraint_source_snapshot_id=_constraint_snapshot(evidence.exit),
        exit_constraint_source_row_sha256=_constraint_row(evidence.exit),
        benchmark_entry_source_snapshot_id=_benchmark_snapshot(evidence.benchmark_entry),
        benchmark_entry_source_row_sha256=_benchmark_row(evidence.benchmark_entry),
        benchmark_exit_source_snapshot_id=_benchmark_snapshot(evidence.benchmark_exit),
        benchmark_exit_source_row_sha256=_benchmark_row(evidence.benchmark_exit),
    )


def _label_value(
    reason: str | None,
    evidence: LabelWindowEvidence,
) -> float | None:
    if reason is not None:
        return None
    if evidence.entry is None or evidence.exit is None:
        detail = "complete stock evidence unexpectedly missing"
        raise LabelInputError(detail)
    if evidence.benchmark_entry is None or evidence.benchmark_exit is None:
        detail = "complete benchmark evidence unexpectedly missing"
        raise LabelInputError(detail)
    if evidence.entry.open_price is None or evidence.exit.open_price is None:
        detail = "complete stock prices unexpectedly missing"
        raise LabelInputError(detail)
    stock_return = evidence.exit.open_price / evidence.entry.open_price - 1.0
    benchmark_return = (
        evidence.benchmark_exit.open_price / evidence.benchmark_entry.open_price - 1.0
    )
    return stock_return - benchmark_return


def _null_reason(
    symbol: str,
    window: LabelWindow,
    evidence: LabelWindowEvidence,
) -> str | None:
    if window.entry_date is None:
        return "NO_ENTRY_SESSION"
    if window.exit_date is None:
        return "NO_EXIT_SESSION"
    return _complete_window_reason(symbol, window, evidence)


def _complete_window_reason(
    symbol: str,
    window: LabelWindow,
    evidence: LabelWindowEvidence,
) -> str | None:
    if window.entry_date is None or window.exit_date is None:
        detail = "complete label window unexpectedly missing"
        raise LabelInputError(detail)
    entry_reason = _trade_reason("ENTRY", symbol, window.entry_date, evidence.entry, is_entry=True)
    if entry_reason is not None:
        return entry_reason
    exit_reason = _trade_reason(
        "EXIT",
        symbol,
        window.exit_date,
        evidence.exit,
        is_entry=False,
    )
    if exit_reason is not None:
        return exit_reason
    if evidence.benchmark_entry is None:
        return "MISSING_BENCHMARK_ENTRY_BAR"
    _validate_benchmark(evidence.benchmark_entry, window.entry_date)
    if evidence.benchmark_exit is None:
        return "MISSING_BENCHMARK_EXIT_BAR"
    _validate_benchmark(evidence.benchmark_exit, window.exit_date)
    return None


def _trade_reason(
    prefix: str,
    symbol: str,
    expected_date: date,
    observation: LabelTradeObservation | None,
    *,
    is_entry: bool,
) -> str | None:
    if observation is None:
        return f"MISSING_{prefix}_BAR"
    if observation.symbol != symbol or observation.trading_date != expected_date:
        detail = f"{prefix.lower()} observation key mismatch"
        raise LabelInputError(detail)
    _validate_clock(observation.available_at)
    if observation.is_suspended:
        return f"{prefix}_SUSPENDED"
    if observation.open_price is None:
        return f"MISSING_{prefix}_BAR"
    _validate_price(observation.open_price, f"{prefix.lower()} open")
    if observation.up_limit is None or observation.down_limit is None:
        return f"MISSING_{prefix}_LIMIT"
    _validate_price(observation.up_limit, f"{prefix.lower()} upper limit")
    _validate_price(observation.down_limit, f"{prefix.lower()} lower limit")
    reason = None
    if is_entry and observation.open_price >= observation.up_limit:
        reason = "ENTRY_LIMIT_UP"
    if not is_entry and observation.open_price <= observation.down_limit:
        reason = "EXIT_LIMIT_DOWN"
    return reason


def _validate_benchmark(observation: BenchmarkOpenObservation, expected_date: date) -> None:
    definition = medium_horizon_label()
    if (
        observation.symbol != definition.benchmark_symbol
        or observation.trading_date != expected_date
    ):
        detail = "benchmark observation key mismatch"
        raise LabelInputError(detail)
    _validate_clock(observation.available_at)
    _validate_price(observation.open_price, "benchmark open")


def _validate_price(value: float, field: str) -> None:
    if not isfinite(value) or value <= 0.0:
        detail = f"{field} must be finite and positive"
        raise LabelInputError(detail)


def _validate_clock(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        detail = "source available_at must be timezone-aware"
        raise LabelInputError(detail)


def _open_time(day: date | None, decision_time: datetime) -> datetime | None:
    if day is None:
        return None
    return datetime.combine(day, time(9, 30), decision_time.tzinfo)


def _label_available_at(
    exit_date: date | None,
    decision_time: datetime,
    evidence: LabelWindowEvidence,
) -> datetime | None:
    if exit_date is None:
        return None
    clocks = [datetime.combine(exit_date, time(18), decision_time.tzinfo)]
    clocks.extend(
        item.available_at
        for item in (
            evidence.entry,
            evidence.exit,
            evidence.benchmark_entry,
            evidence.benchmark_exit,
        )
        if item is not None
    )
    return max(clocks)


def _price_snapshot(item: LabelTradeObservation | None) -> str | None:
    return None if item is None else item.price_source_snapshot_id


def _price_row(item: LabelTradeObservation | None) -> str | None:
    return None if item is None else item.price_source_row_sha256


def _constraint_snapshot(item: LabelTradeObservation | None) -> str | None:
    return None if item is None else item.constraint_source_snapshot_id


def _constraint_row(item: LabelTradeObservation | None) -> str | None:
    return None if item is None else item.constraint_source_row_sha256


def _benchmark_snapshot(item: BenchmarkOpenObservation | None) -> str | None:
    return None if item is None else item.source_snapshot_id


def _benchmark_row(item: BenchmarkOpenObservation | None) -> str | None:
    return None if item is None else item.source_row_sha256
