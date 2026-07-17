"""Build weekly historical stock admission panels from PIT evidence."""

from collections import defaultdict
from datetime import date, datetime
from statistics import median
from typing import Final

from ashare_lab.data.universe import SecurityEvent, SecurityState, replay_security_states
from ashare_lab.research.universe.models import (
    UniverseAdmissionSpec,
    UniverseExclusion,
    UniverseMarketObservation,
    UniversePanelError,
    UniversePanelRow,
    UniversePanelRule,
)

_DEFAULT_SPEC: Final = UniverseAdmissionSpec()


def build_universe_panel(
    events: tuple[SecurityEvent, ...],
    observations: tuple[UniverseMarketObservation, ...],
    open_dates: tuple[date, ...],
    decision_times: tuple[datetime, ...],
    spec: UniverseAdmissionSpec = _DEFAULT_SPEC,
) -> tuple[UniversePanelRow, ...]:
    """Replay every decision with no survivorship or unknown-status deletion."""
    ordered_dates = _validated_open_dates(open_dates)
    market = _market_index(observations)
    rows: list[UniversePanelRow] = []
    for decision_time in decision_times:
        _validate_decision(decision_time, ordered_dates)
        states = replay_security_states(events, decision_time)
        rows.extend(
            _panel_row(state, market.get(state.ts_code, {}), ordered_dates, decision_time, spec)
            for state in states
            if state.listed_at is not None
        )
    return tuple(rows)


def _panel_row(
    state: SecurityState,
    observations: dict[date, UniverseMarketObservation],
    open_dates: tuple[date, ...],
    decision_time: datetime,
    spec: UniverseAdmissionSpec,
) -> UniversePanelRow:
    if not state.listed:
        return UniversePanelRow(
            symbol=state.ts_code,
            decision_time=decision_time,
            available_at=state.latest_available_at,
            eligible_for_new_risk=False,
            must_continue_marking=True,
            reason_codes=(UniverseExclusion.NOT_LISTED.value,),
        )
    listed_at = state.listed_at
    if listed_at is None:
        raise UniversePanelError(UniversePanelRule.MISSING_LISTING_TIME, state.ts_code)
    visible_dates = tuple(day for day in open_dates if day <= decision_time.date())
    listing_sessions = sum(day >= listed_at.date() for day in visible_dates)
    market_window = visible_dates[-spec.market_window_sessions :]
    liquidity_window = visible_dates[-spec.liquidity_window_sessions :]
    visible = {
        day: observation
        for day, observation in observations.items()
        if day <= decision_time.date()
        and observation.available_at <= decision_time
        and observation.quality_status == "ACCEPTED"
    }
    market_count = sum(day in visible for day in market_window)
    liquidity = tuple(visible[day].amount_cny for day in liquidity_window if day in visible)
    reasons = _reasons(state, listing_sessions, market_count, liquidity, spec)
    evidence_times = (state.latest_available_at, *(item.available_at for item in visible.values()))
    return UniversePanelRow(
        symbol=state.ts_code,
        decision_time=decision_time,
        available_at=max(evidence_times),
        eligible_for_new_risk=not reasons,
        must_continue_marking=True,
        reason_codes=tuple(reason.value for reason in reasons),
    )


def _reasons(
    state: SecurityState,
    listing_sessions: int,
    market_count: int,
    liquidity: tuple[float, ...],
    spec: UniverseAdmissionSpec,
) -> tuple[UniverseExclusion, ...]:
    reasons: list[UniverseExclusion] = []
    if not state.status_known:
        reasons.append(UniverseExclusion.UNKNOWN_NAME_STATUS)
    elif state.is_st:
        reasons.append(UniverseExclusion.ST_STATUS)
    if listing_sessions < spec.min_listing_sessions:
        reasons.append(UniverseExclusion.INSUFFICIENT_LISTING_AGE)
    if market_count < spec.min_market_observations:
        reasons.append(UniverseExclusion.INSUFFICIENT_MARKET_HISTORY)
    if len(liquidity) < spec.liquidity_window_sessions:
        reasons.append(UniverseExclusion.INSUFFICIENT_LIQUIDITY_HISTORY)
    elif median(liquidity) < spec.min_median_amount_cny:
        reasons.append(UniverseExclusion.LOW_MEDIAN_AMOUNT)
    return tuple(reasons)


def _market_index(
    observations: tuple[UniverseMarketObservation, ...],
) -> dict[str, dict[date, UniverseMarketObservation]]:
    indexed: defaultdict[str, dict[date, UniverseMarketObservation]] = defaultdict(dict)
    for observation in observations:
        if observation.quality_status != "ACCEPTED":
            continue
        existing = indexed[observation.symbol].get(observation.trading_date)
        if existing is not None:
            raise UniversePanelError(
                UniversePanelRule.DUPLICATE_MARKET_OBSERVATION,
                f"{observation.symbol}:{observation.trading_date:%Y%m%d}",
            )
        indexed[observation.symbol][observation.trading_date] = observation
    return dict(indexed)


def _validated_open_dates(open_dates: tuple[date, ...]) -> tuple[date, ...]:
    if len(open_dates) != len(set(open_dates)):
        detail = "open calendar is not unique"
        raise UniversePanelError(UniversePanelRule.DUPLICATE_OPEN_DATE, detail)
    return tuple(sorted(open_dates))


def _validate_decision(decision_time: datetime, open_dates: tuple[date, ...]) -> None:
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        detail = "decision time has no timezone"
        raise UniversePanelError(UniversePanelRule.NAIVE_DECISION_TIME, detail)
    if decision_time.date() not in set(open_dates):
        raise UniversePanelError(
            UniversePanelRule.CLOSED_DECISION_DATE,
            decision_time.date().isoformat(),
        )
