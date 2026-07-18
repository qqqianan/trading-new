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
