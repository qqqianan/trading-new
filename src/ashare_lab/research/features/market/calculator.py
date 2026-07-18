"""Quality-gated and PIT-safe orchestration of raw market factor formulas."""

from datetime import date, datetime
from math import isfinite

from ashare_lab.research.data_quality import DataQualityGuard
from ashare_lab.research.features.market.calculations import (
    amihud,
    dividend_yield,
    logged_amount_median,
    logged_market_value,
    maximum_drawdown,
    momentum,
    positive_inverse,
    turnover_mean,
    volatility,
)
from ashare_lab.research.features.market.catalog import market_factor_catalog
from ashare_lab.research.features.market.models import (
    FeaturePITError,
    MarketFactorInputError,
    MarketFactorObservation,
    MarketFactorRow,
)


def calculate_market_factors(
    observations: tuple[MarketFactorObservation, ...],
    decision_time: datetime,
    expected_trading_dates: tuple[date, ...] | None = None,
) -> tuple[MarketFactorRow, ...]:
    """Run hard quality/PIT gates and emit every registered factor row."""
    _validate_inputs(observations, decision_time)
    prices = tuple(item.bar.close * item.adjustment_factor for item in observations)
    latest = observations[-1]
    calculated = (
        momentum(prices, 20),
        momentum(prices, 60),
        momentum(prices, 120),
        _negated(momentum(prices, 5)),
        volatility(prices, 20),
        volatility(prices, 60),
        maximum_drawdown(prices, 60),
        turnover_mean(observations),
        logged_amount_median(observations),
        amihud(observations),
        logged_market_value(latest.total_mv_ten_thousand_cny),
        positive_inverse(latest.pe_ttm),
        positive_inverse(latest.pb),
        positive_inverse(latest.ps_ttm),
        dividend_yield(latest.dv_ttm_percent),
    )
    definitions = market_factor_catalog()
    gap_flags = tuple(
        _has_window_gap(definition.name, observations, expected_trading_dates)
        for definition in definitions
    )
    values = tuple(
        None if has_gap else value for value, has_gap in zip(calculated, gap_flags, strict=True)
    )
    return tuple(
        MarketFactorRow(
            symbol=str(latest.bar.symbol),
            decision_time=decision_time,
            feature_id=definition.name,
            feature_version=definition.version,
            value=value,
            available_at=max(item.bar.available_at for item in observations),
            quality_status="ACCEPTED" if value is not None else "INCOMPLETE",
            null_reason=_null_reason(
                definition.name,
                observations,
                value,
                has_window_gap=has_gap,
            ),
        )
        for definition, value, has_gap in zip(definitions, values, gap_flags, strict=True)
    )


def _validate_inputs(
    observations: tuple[MarketFactorObservation, ...],
    decision_time: datetime,
) -> None:
    if not observations:
        detail = "factor observation series is empty"
        raise MarketFactorInputError(detail)
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        detail = "decision_time must be timezone-aware"
        raise MarketFactorInputError(detail)
    DataQualityGuard().validate(tuple(item.bar for item in observations))
    for item in observations:
        if item.bar.available_at > decision_time:
            raise FeaturePITError(item.bar.available_at, decision_time)
        if not isfinite(item.adjustment_factor) or item.adjustment_factor <= 0.0:
            detail = "adjustment_factor must be finite and positive"
            raise MarketFactorInputError(detail)
        if not isfinite(item.amount_cny) or item.amount_cny < 0.0:
            detail = "amount_cny must be finite and non-negative"
            raise MarketFactorInputError(detail)


def _negated(value: float | None) -> float | None:
    return -value if value is not None else None


def _null_reason(
    feature_id: str,
    observations: tuple[MarketFactorObservation, ...],
    value: float | None,
    *,
    has_window_gap: bool,
) -> str | None:
    if value is not None:
        return None
    if has_window_gap:
        return "MISSING_TRADING_SESSION"
    required = _required_observations(feature_id)
    if len(observations) < required:
        return "INSUFFICIENT_HISTORY"
    latest = observations[-1]
    denominator_values = {
        "earnings_yield_ttm": latest.pe_ttm,
        "book_yield": latest.pb,
        "sales_yield_ttm": latest.ps_ttm,
        "log_total_mv": latest.total_mv_ten_thousand_cny,
    }
    denominator = denominator_values.get(feature_id)
    if feature_id in denominator_values:
        return _denominator_reason(denominator)
    reasons = {
        "turnover_mean_20": "SOURCE_VALUE_MISSING",
        "amihud_20": "NON_POSITIVE_AMOUNT",
        "dividend_yield_ttm": (
            "SOURCE_VALUE_MISSING" if latest.dv_ttm_percent is None else "SOURCE_VALUE_INVALID"
        ),
    }
    return reasons.get(feature_id, "SOURCE_VALUE_INVALID")


def _denominator_reason(value: float | None) -> str:
    return "SOURCE_VALUE_MISSING" if value is None else "NON_POSITIVE_DENOMINATOR"


def _has_window_gap(
    feature_id: str,
    observations: tuple[MarketFactorObservation, ...],
    expected_dates: tuple[date, ...] | None,
) -> bool:
    if expected_dates is None:
        return False
    required = _required_observations(feature_id)
    if len(expected_dates) < required:
        return False
    expected = set(expected_dates[-required:])
    observed = {item.bar.trading_date for item in observations}
    return not expected.issubset(observed)


def _required_observations(feature_id: str) -> int:
    lookback = next(
        item.lookback_trading_days for item in market_factor_catalog() if item.name == feature_id
    )
    return_factor_ids = {"mom_20", "mom_60", "mom_120", "reversal_5", "vol_20", "vol_60"}
    return lookback + 1 if feature_id in return_factor_ids else lookback
