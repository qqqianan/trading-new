"""Pure formula implementations for the fixed market factor catalog."""

from itertools import pairwise
from math import log, log1p
from statistics import fmean, median, stdev
from typing import Final

from ashare_lab.research.features.market.models import MarketFactorObservation

_LIQUIDITY_WINDOW: Final = 20


def momentum(prices: tuple[float, ...], periods: int) -> float | None:
    """Return a simple adjusted-price return over an exact session lag."""
    if len(prices) < periods + 1:
        return None
    return (prices[-1] / prices[-periods - 1]) - 1.0


def volatility(prices: tuple[float, ...], periods: int) -> float | None:
    """Return sample standard deviation of adjusted daily returns."""
    if len(prices) < periods + 1:
        return None
    window = prices[-periods - 1 :]
    returns = tuple((current / previous) - 1.0 for previous, current in pairwise(window))
    return stdev(returns)


def maximum_drawdown(prices: tuple[float, ...], sessions: int) -> float | None:
    """Return the most negative peak-to-trough return in a price window."""
    if len(prices) < sessions:
        return None
    peak = prices[-sessions]
    drawdown = 0.0
    for price in prices[-sessions:]:
        peak = max(peak, price)
        drawdown = min(drawdown, (price / peak) - 1.0)
    return drawdown


def turnover_mean(observations: tuple[MarketFactorObservation, ...]) -> float | None:
    """Return the 20-session mean provider turnover percentage."""
    if len(observations) < _LIQUIDITY_WINDOW:
        return None
    values = tuple(item.turnover_rate for item in observations[-_LIQUIDITY_WINDOW:])
    if any(value is None for value in values):
        return None
    return fmean(value for value in values if value is not None)


def logged_amount_median(observations: tuple[MarketFactorObservation, ...]) -> float | None:
    """Return log1p of the 20-session median amount in yuan."""
    if len(observations) < _LIQUIDITY_WINDOW:
        return None
    return log1p(median(item.amount_cny for item in observations[-_LIQUIDITY_WINDOW:]))


def amihud(observations: tuple[MarketFactorObservation, ...]) -> float | None:
    """Return mean absolute raw return divided by amount in yuan."""
    if len(observations) < _LIQUIDITY_WINDOW or any(
        item.amount_cny <= 0.0 for item in observations[-_LIQUIDITY_WINDOW:]
    ):
        return None
    return fmean(
        abs((item.bar.close / item.bar.previous_close) - 1.0) / item.amount_cny
        for item in observations[-_LIQUIDITY_WINDOW:]
    )


def logged_market_value(value: float | None) -> float | None:
    """Convert ten-thousand yuan to yuan before taking natural log."""
    if value is None or value <= 0.0:
        return None
    return log(value * 10_000.0)


def positive_inverse(value: float | None) -> float | None:
    """Invert only positive valuation ratios without absolute-value repair."""
    if value is None or value <= 0.0:
        return None
    return 1.0 / value


def dividend_yield(value: float | None) -> float | None:
    """Convert provider percent into decimal return units."""
    if value is None or value < 0.0:
        return None
    return value / 100.0
