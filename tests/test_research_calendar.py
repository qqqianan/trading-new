from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.research.calendar import weekly_decision_times

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_weekly_decisions_use_the_last_open_session_of_each_iso_week() -> None:
    # Given: two trading weeks where Friday is closed in the second week.
    open_dates = (
        date(2026, 7, 13),
        date(2026, 7, 14),
        date(2026, 7, 15),
        date(2026, 7, 16),
        date(2026, 7, 17),
        date(2026, 7, 20),
        date(2026, 7, 21),
        date(2026, 7, 22),
        date(2026, 7, 23),
    )

    # When: the governed calendar is reduced to weekly decisions.
    decisions = weekly_decision_times(open_dates)

    # Then: each decision occurs after the final open close, never on a closed Friday.
    assert decisions == (
        datetime(2026, 7, 17, 18, tzinfo=SHANGHAI),
        datetime(2026, 7, 23, 18, tzinfo=SHANGHAI),
    )


def test_weekly_decisions_reject_duplicate_calendar_dates() -> None:
    # Given: a calendar containing duplicate accepted open dates.
    duplicated = (date(2026, 7, 17), date(2026, 7, 17))

    # When / Then: research scheduling fails closed on ambiguous evidence.
    with pytest.raises(ValueError, match="duplicate"):
        weekly_decision_times(duplicated)
