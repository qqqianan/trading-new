from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.universe import SecurityEvent, SecurityEventType
from ashare_lab.research.universe import (
    UniverseAdmissionSpec,
    UniverseMarketObservation,
    UniversePanelError,
    build_universe_panel,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_unknown_historical_status_is_retained_but_cannot_take_new_risk() -> None:
    # Given: a long-listed symbol with sufficient liquidity but no historical name evidence.
    dates = _open_dates(130)
    decision = _decision(dates[-1])
    events = (_event(SecurityEventType.LISTED, dates[0]),)

    # When: the weekly PIT universe is built.
    row = build_universe_panel(events, _market("000001.SZ", dates), dates, (decision,))[0]

    # Then: unknown ST status fails closed without deleting mark-to-market responsibility.
    assert row.eligible_for_new_risk is False
    assert row.must_continue_marking is True
    assert row.reason_codes == ("UNKNOWN_NAME_STATUS",)


def test_eligible_symbol_passes_age_history_status_and_liquidity_rules() -> None:
    # Given: 130 open sessions, known non-ST status, and liquid accepted observations.
    dates = _open_dates(130)
    decision = _decision(dates[-1])
    events = (
        _event(SecurityEventType.LISTED, dates[0]),
        _event(SecurityEventType.NAME_STATUS, dates[0], name="平安银行", is_st=False),
    )

    # When: the fixed first-version admission rules are applied.
    row = build_universe_panel(events, _market("000001.SZ", dates), dates, (decision,))[0]

    # Then: the symbol is eligible and every evidence clock is PIT-safe.
    assert row.eligible_for_new_risk is True
    assert row.reason_codes == ()
    assert row.available_at <= row.decision_time


def test_delisted_symbol_remains_in_panel_for_position_marking() -> None:
    # Given: a formerly listed symbol whose delisting is visible by the decision time.
    dates = _open_dates(130)
    decision = _decision(dates[-1])
    events = (
        _event(SecurityEventType.LISTED, dates[0]),
        _event(SecurityEventType.NAME_STATUS, dates[0], name="退市样本", is_st=False),
        _event(SecurityEventType.DELISTED, dates[-2]),
    )

    # When: historical state is replayed without survivorship filtering.
    row = build_universe_panel(events, _market("000001.SZ", dates), dates, (decision,))[0]

    # Then: new risk is forbidden but a held position cannot disappear from accounting.
    assert row.eligible_for_new_risk is False
    assert row.must_continue_marking is True
    assert row.reason_codes == ("NOT_LISTED",)


def test_admission_rule_change_produces_a_new_universe_version() -> None:
    # Given: the fixed first-version admission contract.
    original = UniverseAdmissionSpec()

    # When: one material liquidity threshold changes.
    changed = UniverseAdmissionSpec(min_median_amount_cny=30_000_000.0)

    # Then: downstream DatasetSpec cannot confuse the two universes.
    assert original.version_id != changed.version_id


def test_duplicate_market_observation_is_rejected() -> None:
    # Given: two accepted rows for one symbol and trading date.
    dates = _open_dates(130)
    observations = _market("000001.SZ", dates)
    duplicated = (*observations, observations[-1])

    # When / Then: the panel refuses ambiguous market history.
    with pytest.raises(UniversePanelError, match="duplicate_market_observation"):
        build_universe_panel(
            (_event(SecurityEventType.LISTED, dates[0]),),
            duplicated,
            dates,
            (_decision(dates[-1]),),
        )


def _open_dates(count: int) -> tuple[date, ...]:
    values: list[date] = []
    current = date(2025, 1, 2)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


def _decision(day: date) -> datetime:
    return datetime.combine(day, time(18), SHANGHAI)


def _event(
    event_type: SecurityEventType,
    day: date,
    *,
    name: str | None = None,
    is_st: bool | None = None,
) -> SecurityEvent:
    at = datetime.combine(day, time(9, 25), SHANGHAI)
    identity = f"{event_type.value}_{day:%Y%m%d}_{name or 'none'}"
    return SecurityEvent(
        event_id=identity,
        ts_code="000001.SZ",
        event_type=event_type,
        effective_at=at,
        available_at=at,
        ingested_at=at,
        name=name,
        is_st=is_st,
        source_endpoint="fixture",
        source_snapshot_id=f"snapshot_{identity}",
        source_row_sha256="a" * 64,
        input_schema_manifest_id="schema_input",
        schema_manifest_id="schema_universe",
        transform_name="fixture",
        transform_version="1.0.0",
        quality_status="ACCEPTED",
        quality_report_id=f"quality_{identity}",
    )


def _market(symbol: str, dates: tuple[date, ...]) -> tuple[UniverseMarketObservation, ...]:
    return tuple(
        UniverseMarketObservation(
            symbol=symbol,
            trading_date=day,
            available_at=datetime.combine(day, time(16), SHANGHAI),
            amount_cny=25_000_000.0,
            quality_status="ACCEPTED",
            source_artifact_id=f"daily_{day:%Y%m%d}",
        )
        for day in dates
    )
