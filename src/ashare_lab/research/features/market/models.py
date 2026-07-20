"""Typed inputs and long-form outputs for governed market factors."""

from dataclasses import dataclass
from datetime import datetime

from ashare_lab.domain.market import MarketBar


@dataclass(frozen=True, slots=True)
class MarketFactorObservation:
    """One quality-guarded daily bundle used only after its availability time."""

    bar: MarketBar
    adjustment_factor: float
    turnover_rate: float | None
    amount_cny: float
    total_mv_ten_thousand_cny: float | None
    pe_ttm: float | None
    pb: float | None
    ps_ttm: float | None
    dv_ttm_percent: float | None
    source_artifact_ids: tuple[str, ...]
    source_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketFactorRow:
    """One registered raw feature value at one decision time."""

    symbol: str
    decision_time: datetime
    feature_id: str
    feature_version: str
    value: float | None
    available_at: datetime
    quality_status: str
    null_reason: str | None


class FeaturePITError(Exception):
    """A market source became available after the decision boundary."""

    __slots__ = ("available_at", "decision_time")

    def __init__(self, available_at: datetime, decision_time: datetime) -> None:
        """Record the leaked source and claimed decision clocks."""
        super().__init__()
        self.available_at = available_at
        self.decision_time = decision_time

    def __str__(self) -> str:
        """Return a stable leakage rule and both clocks."""
        return (
            "available_after_decision: "
            f"{self.available_at.isoformat()} > {self.decision_time.isoformat()}"
        )


class MarketFactorInputError(Exception):
    """A required non-price factor input violates its physical domain."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record the rejected source field or batch shape."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable input rule and concrete detail."""
        return f"market_factor_input: {self.detail}"
