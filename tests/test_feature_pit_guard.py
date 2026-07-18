from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.research.features.market import FeaturePITError, calculate_market_factors
from tests.test_market_factors import market_observations

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_market_factor_batch_rejects_any_observation_available_after_decision() -> None:
    # Given: one required source row published after the claimed decision time.
    observations = market_observations(21)
    decision = datetime.combine(observations[-1].bar.trading_date, time(18), SHANGHAI)
    leaked_bar = replace(observations[-1].bar, available_at=decision + timedelta(minutes=1))
    leaked = (*observations[:-1], replace(observations[-1], bar=leaked_bar))

    # When / Then: the entire feature batch fails instead of nulling or hiding the leak.
    with pytest.raises(FeaturePITError, match="available_after_decision"):
        calculate_market_factors(leaked, decision)


def test_market_factor_window_preserves_null_when_expected_session_is_missing() -> None:
    # Given: enough observed rows by count but one expected market session is absent.
    observations = market_observations(21)
    decision = datetime.combine(observations[-1].bar.trading_date, time(18), SHANGHAI)
    observed_dates = tuple(item.bar.trading_date for item in observations)
    friday = next(day for day in observed_dates[:-1] if day.weekday() == 4)
    expected = list(observed_dates)
    expected[expected.index(friday)] = friday + timedelta(days=1)
    expected_dates = tuple(sorted(expected))

    # When: the calculator receives the governed calendar window.
    rows = calculate_market_factors(observations, decision, expected_dates)
    indexed = {row.feature_id: row for row in rows}

    # Then: rolling momentum is null, while current-date size remains usable.
    assert indexed["mom_20"].value is None
    assert indexed["mom_20"].null_reason == "MISSING_TRADING_SESSION"
    assert indexed["log_total_mv"].value is not None
