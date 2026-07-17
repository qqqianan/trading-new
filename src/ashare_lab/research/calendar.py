"""Governed weekly decision clock derived from accepted open sessions."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DECISION_CLOCK = time(18)


def weekly_decision_times(
    open_dates: tuple[date, ...],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[datetime, ...]:
    """Select each ISO week's final open session after provider publication."""
    if len(open_dates) != len(set(open_dates)):
        detail = "governed open calendar contains duplicate dates"
        raise ValueError(detail)
    weekly: dict[tuple[int, int], date] = {}
    for day in sorted(open_dates):
        iso = day.isocalendar()
        weekly[(iso.year, iso.week)] = day
    return tuple(
        datetime.combine(day, _DECISION_CLOCK, _SHANGHAI)
        for day in weekly.values()
        if (start_date is None or day >= start_date) and (end_date is None or day <= end_date)
    )
