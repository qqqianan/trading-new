"""Typed PIT inputs, outputs, and failures for financial factors."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FinancialIndicatorObservation:
    """One accepted immutable financial-indicator publication version."""

    event_id: str
    symbol: str
    available_at: datetime
    report_period: str
    update_flag: str | None
    roe: float | None
    grossprofit_margin: float | None
    ocf_to_debt: float | None
    debt_to_assets: float | None
    q_sales_yoy: float | None
    q_netprofit_yoy: float | None
    source_snapshot_id: str
    source_row_sha256: str


@dataclass(frozen=True, slots=True)
class FinancialFactorValue:
    """One raw financial factor with exact selected-version provenance."""

    symbol: str
    decision_time: datetime
    feature_id: str
    feature_version: str
    value: float | None
    available_at: datetime
    quality_status: str
    null_reason: str | None
    source_event_id: str | None
    source_report_period: str | None
    source_available_at: datetime | None
    source_update_flag: str | None
    source_snapshot_id: str | None
    source_row_sha256: str | None


class FinancialVersionConflictError(Exception):
    """One PIT version key carries materially different accepted facts."""

    __slots__ = ("available_at", "report_period", "symbol")

    def __init__(self, symbol: str, report_period: str, available_at: datetime) -> None:
        """Record the ambiguous version key without selecting an event."""
        super().__init__()
        self.symbol = symbol
        self.report_period = report_period
        self.available_at = available_at

    def __str__(self) -> str:
        """Return a stable conflict rule and natural version key."""
        return (
            "financial_version_conflict: "
            f"{self.symbol}:{self.report_period}:{self.available_at.isoformat()}"
        )


class FinancialFactorInputError(Exception):
    """Financial PIT evidence violates a required physical or time domain."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record the rejected evidence detail."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable input rule and evidence detail."""
        return f"financial_factor_input: {self.detail}"
