from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest

from ashare_lab.domain.market import MarketBar, PriceBasis, Symbol
from ashare_lab.research.data_quality import (
    DataIntegrityError,
    DataQualityGuard,
    TemporalLeakageError,
)


def _bar(day: int, *, available_hour: int = 15) -> MarketBar:
    trading_date = date(2025, 1, 2) + timedelta(days=day)
    return MarketBar(
        symbol=Symbol("600000.SH"),
        trading_date=trading_date,
        available_at=datetime.combine(
            trading_date,
            time(available_hour, 5),
            tzinfo=UTC,
        ),
        price_basis=PriceBasis.RAW,
        open=10.0,
        high=10.5,
        low=9.5,
        close=10.2,
        volume=1_000_000,
        previous_close=10.0,
        limit_up=11.0,
        limit_down=9.0,
        is_suspended=False,
    )


def test_quality_guard_rejects_duplicate_trading_dates() -> None:
    # Given: two observations with the same symbol and trading date.
    duplicate = _bar(0)

    # When / Then: the series is rejected before research can consume it.
    with pytest.raises(DataIntegrityError, match="strictly increasing"):
        DataQualityGuard().validate((duplicate, duplicate))


def test_quality_guard_rejects_invalid_ohlc_relationship() -> None:
    # Given: a close above the reported daily high.
    invalid = replace(_bar(0), close=11.0)

    # When / Then: corrupt price geometry is rejected.
    with pytest.raises(DataIntegrityError, match="OHLC"):
        DataQualityGuard().validate((invalid,))


def test_quality_guard_rejects_data_revised_after_next_open() -> None:
    # Given: day-zero data only became available after the next session opened.
    first = replace(
        _bar(0),
        available_at=datetime.combine(_bar(1).trading_date, time(10, 0), tzinfo=UTC),
    )

    # When / Then: using the revision for a next-open order is temporal leakage.
    with pytest.raises(TemporalLeakageError, match="next execution time"):
        DataQualityGuard().validate((first, _bar(1)))


def test_quality_report_marks_valid_raw_series_as_point_in_time() -> None:
    # Given: ordered raw bars available before the next execution time.
    bars = (_bar(0), _bar(1), _bar(2))

    # When: the hard data gate runs.
    report = DataQualityGuard().validate(bars)

    # Then: an auditable point-in-time report is returned.
    assert report.passed is True
    assert report.bar_count == 3
    assert report.price_basis is PriceBasis.RAW
    assert report.point_in_time is True
