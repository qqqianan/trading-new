from datetime import date, datetime, time, timedelta
from math import isclose, log, log1p
from zoneinfo import ZoneInfo

from ashare_lab.domain.market import MarketBar, PriceBasis, Symbol
from ashare_lab.research.features.market import (
    MarketFactorObservation,
    calculate_market_factors,
    market_factor_catalog,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_market_factor_catalog_registers_the_fixed_fifteen_features() -> None:
    # Given / When: the first governed non-financial feature catalog is loaded.
    catalog = market_factor_catalog()

    # Then: model adapters receive a closed, versioned feature set.
    assert tuple(item.name for item in catalog) == (
        "mom_20",
        "mom_60",
        "mom_120",
        "reversal_5",
        "vol_20",
        "vol_60",
        "max_drawdown_60",
        "turnover_mean_20",
        "amount_median_20",
        "amihud_20",
        "log_total_mv",
        "earnings_yield_ttm",
        "book_yield",
        "sales_yield_ttm",
        "dividend_yield_ttm",
    )
    assert catalog[0].lookback_trading_days == 20
    assert catalog[2].lookback_trading_days == 120


def test_market_factors_match_hand_calculated_monotonic_fixture() -> None:
    # Given: 121 accepted sessions with 1% daily returns and fixed fundamentals.
    observations = market_observations(121)
    decision = datetime.combine(observations[-1].bar.trading_date, time(18), SHANGHAI)

    # When: all fixed market factor definitions are evaluated.
    rows = calculate_market_factors(observations, decision)
    values = {row.feature_id: row.value for row in rows}

    # Then: window, unit conversion, and denominator semantics match hand calculations.
    assert len(rows) == 15
    assert isclose(_value(values["mom_20"]), (1.01**20) - 1.0, rel_tol=1e-12)
    assert isclose(_value(values["mom_120"]), (1.01**120) - 1.0, rel_tol=1e-12)
    assert isclose(_value(values["reversal_5"]), -((1.01**5) - 1.0), rel_tol=1e-12)
    assert abs(_value(values["vol_20"])) < 1e-12
    assert _value(values["max_drawdown_60"]) == 0.0
    assert _value(values["turnover_mean_20"]) == 2.0
    assert isclose(_value(values["amount_median_20"]), log1p(25_000_000.0))
    assert isclose(_value(values["amihud_20"]), 0.01 / 25_000_000.0, rel_tol=1e-12)
    assert isclose(_value(values["log_total_mv"]), log(1_000_000.0 * 10_000.0))
    assert _value(values["earnings_yield_ttm"]) == 0.05
    assert _value(values["book_yield"]) == 0.25
    assert _value(values["sales_yield_ttm"]) == 0.1
    assert _value(values["dividend_yield_ttm"]) == 0.03


def test_market_factors_keep_nulls_for_short_windows_and_invalid_valuations() -> None:
    # Given: only ten observations and non-positive valuation denominators.
    observations = market_observations(10, pe_ttm=-20.0, pb=0.0, ps_ttm=None)
    decision = datetime.combine(observations[-1].bar.trading_date, time(18), SHANGHAI)

    # When: the complete fixed catalog is materialized without sample deletion.
    rows = calculate_market_factors(observations, decision)
    indexed = {row.feature_id: row for row in rows}

    # Then: every feature row remains present with stable missing-value reasons.
    assert len(rows) == 15
    assert indexed["mom_20"].value is None
    assert indexed["mom_20"].null_reason == "INSUFFICIENT_HISTORY"
    assert indexed["earnings_yield_ttm"].null_reason == "NON_POSITIVE_DENOMINATOR"
    assert indexed["book_yield"].null_reason == "NON_POSITIVE_DENOMINATOR"
    assert indexed["sales_yield_ttm"].null_reason == "SOURCE_VALUE_MISSING"


def market_observations(
    count: int,
    *,
    pe_ttm: float | None = 20.0,
    pb: float | None = 4.0,
    ps_ttm: float | None = 10.0,
) -> tuple[MarketFactorObservation, ...]:
    dates = _open_dates(count)
    price = 10.0
    rows: list[MarketFactorObservation] = []
    for index, day in enumerate(dates):
        previous = price
        price = 10.0 if index == 0 else price * 1.01
        rows.append(
            MarketFactorObservation(
                bar=MarketBar(
                    symbol=Symbol("000001.SZ"),
                    trading_date=day,
                    available_at=datetime.combine(day, time(16), SHANGHAI),
                    price_basis=PriceBasis.RAW,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=1_000_000,
                    previous_close=previous,
                    limit_up=price * 1.1,
                    limit_down=price * 0.9,
                    is_suspended=False,
                ),
                adjustment_factor=1.0,
                turnover_rate=2.0,
                amount_cny=25_000_000.0,
                total_mv_ten_thousand_cny=1_000_000.0,
                pe_ttm=pe_ttm,
                pb=pb,
                ps_ttm=ps_ttm,
                dv_ttm_percent=3.0,
                source_artifact_ids=(f"daily_{day:%Y%m%d}",),
                source_snapshot_ids=(f"snapshot_{day:%Y%m%d}",),
            )
        )
    return tuple(rows)


def _open_dates(count: int) -> tuple[date, ...]:
    values: list[date] = []
    current = date(2025, 1, 2)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


def _value(value: float | None) -> float:
    assert value is not None
    return value
