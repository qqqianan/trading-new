"""Closed contracts for weekly point-in-time universe materialization."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique


@dataclass(frozen=True, slots=True)
class UniverseAdmissionSpec:
    """Versioned medium-horizon stock admission parameters."""

    rule_version: str = "1.0.0"
    min_listing_sessions: int = 120
    market_window_sessions: int = 60
    min_market_observations: int = 50
    liquidity_window_sessions: int = 20
    min_median_amount_cny: float = 20_000_000.0

    @property
    def version_id(self) -> str:
        """Content-address every material admission parameter."""
        identity = "|".join(
            (
                self.rule_version,
                str(self.min_listing_sessions),
                str(self.market_window_sessions),
                str(self.min_market_observations),
                str(self.liquidity_window_sessions),
                format(self.min_median_amount_cny, ".6f"),
            )
        )
        return f"universe_rules_{hashlib.sha256(identity.encode()).hexdigest()}"


@dataclass(frozen=True, slots=True)
class UniverseMarketObservation:
    """One quality-governed daily amount observation used for admission."""

    symbol: str
    trading_date: date
    available_at: datetime
    amount_cny: float
    quality_status: str
    source_artifact_id: str


@dataclass(frozen=True, slots=True)
class UniversePanelRow:
    """One decision-time state preserving both entry and accounting duties."""

    symbol: str
    decision_time: datetime
    available_at: datetime
    eligible_for_new_risk: bool
    must_continue_marking: bool
    reason_codes: tuple[str, ...]


@unique
class UniverseExclusion(StrEnum):
    """Stable fail-closed admission reason codes."""

    NOT_LISTED = "NOT_LISTED"
    UNKNOWN_NAME_STATUS = "UNKNOWN_NAME_STATUS"
    ST_STATUS = "ST_STATUS"
    INSUFFICIENT_LISTING_AGE = "INSUFFICIENT_LISTING_AGE"
    INSUFFICIENT_MARKET_HISTORY = "INSUFFICIENT_MARKET_HISTORY"
    INSUFFICIENT_LIQUIDITY_HISTORY = "INSUFFICIENT_LIQUIDITY_HISTORY"
    LOW_MEDIAN_AMOUNT = "LOW_MEDIAN_AMOUNT"


@unique
class UniversePanelRule(StrEnum):
    """Stable evidence failures that stop universe materialization."""

    CLOSED_DECISION_DATE = "closed_decision_date"
    DUPLICATE_MARKET_OBSERVATION = "duplicate_market_observation"
    DUPLICATE_OPEN_DATE = "duplicate_open_date"
    MISSING_LISTING_TIME = "missing_listing_time"
    NAIVE_DECISION_TIME = "naive_decision_time"


class UniversePanelError(Exception):
    """Governed evidence cannot produce an unambiguous PIT universe."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: UniversePanelRule, detail: str) -> None:
        """Create a stable fail-closed panel error."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the rule code and concrete evidence detail."""
        return f"{self.rule.value}: {self.detail}"
