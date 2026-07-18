"""Validated market evidence indexing and bounded rolling-history carry."""

from collections import defaultdict
from dataclasses import replace
from datetime import date

from ashare_lab.research.features.market.calculator import calculate_market_factors
from ashare_lab.research.features.market.catalog import market_factor_catalog
from ashare_lab.research.features.market.models import (
    MarketFactorObservation,
    MarketFactorRow,
)
from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleReadResult,
    MarketKey,
)
from ashare_lab.services.market_feature_contracts import (
    MarketFeatureServiceError,
    MarketFeatureServiceRule,
    UniverseFeatureKey,
)

type MarketHistory = dict[str, tuple[MarketFactorObservation, ...]]


def prepare_market_evidence(
    evidence: MarketBundleReadResult,
) -> tuple[MarketHistory, set[MarketKey]]:
    """Index one read batch after rejecting duplicate natural keys."""
    suspended = set(evidence.suspended_keys)
    indexed: dict[MarketKey, MarketFactorObservation] = {}
    for item in evidence.observations:
        key = (str(item.bar.symbol), item.bar.trading_date)
        if key in indexed:
            raise MarketFeatureServiceError(
                MarketFeatureServiceRule.DUPLICATE_MARKET_OBSERVATION,
                f"{key[0]}:{key[1]:%Y%m%d}",
            )
        indexed[key] = (
            replace(item, bar=replace(item.bar, is_suspended=True)) if key in suspended else item
        )
    grouped: defaultdict[str, list[MarketFactorObservation]] = defaultdict(list)
    for (symbol, _), item in sorted(indexed.items()):
        grouped[symbol].append(item)
    rejected = {(item.symbol, item.trading_date) for item in evidence.rejections}
    return {symbol: tuple(values) for symbol, values in grouped.items()}, rejected


def merge_market_history(carry: MarketHistory, current: MarketHistory) -> MarketHistory:
    """Merge disjoint consecutive batches and reject accidental overlap."""
    merged: dict[str, tuple[MarketFactorObservation, ...]] = {}
    for symbol in carry.keys() | current.keys():
        series = (*carry.get(symbol, ()), *current.get(symbol, ()))
        dates = tuple(item.bar.trading_date for item in series)
        if len(dates) != len(set(dates)):
            duplicate = next(day for index, day in enumerate(dates) if day in dates[:index])
            raise MarketFeatureServiceError(
                MarketFeatureServiceRule.DUPLICATE_MARKET_OBSERVATION,
                f"{symbol}:{duplicate:%Y%m%d}",
            )
        merged[symbol] = tuple(sorted(series, key=lambda item: item.bar.trading_date))
    return merged


def retain_market_history(
    history: MarketHistory,
    calendar: tuple[date, ...],
    batch_end: date,
) -> MarketHistory:
    """Carry only the last 120 governed sessions into the next batch."""
    retained_dates = set(tuple(day for day in calendar if day <= batch_end)[-120:])
    return {
        symbol: tuple(item for item in series if item.bar.trading_date in retained_dates)
        for symbol, series in history.items()
    }


def market_factor_rows(
    keys: tuple[UniverseFeatureKey, ...],
    expected_dates: tuple[date, ...],
    observations: MarketHistory,
    rejected: set[MarketKey],
) -> tuple[MarketFactorRow, ...]:
    """Calculate or explicitly null every universe key and registered factor."""
    expected = set(expected_dates)
    rows: list[MarketFactorRow] = []
    for key in keys:
        series = tuple(
            item for item in observations.get(key.symbol, ()) if item.bar.trading_date in expected
        )
        current_key = (key.symbol, key.decision_time.date())
        if not series or series[-1].bar.trading_date != key.decision_time.date():
            reason = (
                "MISSING_REQUIRED_BUNDLE" if current_key in rejected else "MISSING_DECISION_BAR"
            )
            rows.extend(_null_rows(key, reason))
            continue
        rows.extend(calculate_market_factors(series, key.decision_time, expected_dates))
    return tuple(rows)


def _null_rows(key: UniverseFeatureKey, reason: str) -> tuple[MarketFactorRow, ...]:
    return tuple(
        MarketFactorRow(
            symbol=key.symbol,
            decision_time=key.decision_time,
            feature_id=definition.name,
            feature_version=definition.version,
            value=None,
            available_at=key.available_at,
            quality_status="INCOMPLETE",
            null_reason=reason,
        )
        for definition in market_factor_catalog()
    )
