"""Typed future-window evidence and physically isolated label rows."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class LabelWindow:
    """Fixed t+1 entry and t+21 exit sessions from a governed calendar."""

    entry_date: date | None
    exit_date: date | None


@dataclass(frozen=True, slots=True)
class LabelTradeObservation:
    """One stock open and its same-session execution constraint evidence."""

    symbol: str
    trading_date: date
    open_price: float | None
    up_limit: float | None
    down_limit: float | None
    is_suspended: bool
    available_at: datetime
    price_source_snapshot_id: str | None
    price_source_row_sha256: str | None
    constraint_source_snapshot_id: str | None
    constraint_source_row_sha256: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkOpenObservation:
    """One accepted raw benchmark open with exact source identity."""

    symbol: str
    trading_date: date
    open_price: float
    available_at: datetime
    source_snapshot_id: str
    source_row_sha256: str


@dataclass(frozen=True, slots=True)
class LabelWindowEvidence:
    """Four fixed-session observations consumed by one target calculation."""

    entry: LabelTradeObservation | None
    exit: LabelTradeObservation | None
    benchmark_entry: BenchmarkOpenObservation | None
    benchmark_exit: BenchmarkOpenObservation | None


@dataclass(frozen=True, slots=True)
class RelativeReturnLabelRow:
    """One future target kept physically separate from every feature row."""

    symbol: str
    decision_time: datetime
    entry_time: datetime | None
    exit_time: datetime | None
    label_id: str
    label_version: str
    value: float | None
    available_at: datetime | None
    null_reason: str | None
    entry_price_source_snapshot_id: str | None
    entry_price_source_row_sha256: str | None
    entry_constraint_source_snapshot_id: str | None
    entry_constraint_source_row_sha256: str | None
    exit_price_source_snapshot_id: str | None
    exit_price_source_row_sha256: str | None
    exit_constraint_source_snapshot_id: str | None
    exit_constraint_source_row_sha256: str | None
    benchmark_entry_source_snapshot_id: str | None
    benchmark_entry_source_row_sha256: str | None
    benchmark_exit_source_snapshot_id: str | None
    benchmark_exit_source_row_sha256: str | None


class LabelInputError(Exception):
    """Calendar or future-price evidence violates the fixed label contract."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record the rejected evidence detail."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable label input rule and detail."""
        return f"label_input: {self.detail}"


class LabelReaderError(Exception):
    """The Mongo label boundary is outside the governed database contract."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record the rejected database or evidence detail."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable reader failure and detail."""
        return f"label_reader: {self.detail}"
