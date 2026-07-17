"""Deterministic synthetic daily data for zero-configuration evaluation."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import sin
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np

from ashare_lab.domain.market import Instrument, MarketBar, PriceBasis, Symbol

_INSTRUMENTS: Final = (
    Instrument(Symbol("600519.SH"), "贵州茅台", "上交所", "主板"),
    Instrument(Symbol("000858.SZ"), "五粮液", "深交所", "主板"),
    Instrument(Symbol("600036.SH"), "招商银行", "上交所", "主板"),
    Instrument(Symbol("300750.SZ"), "宁德时代", "深交所", "创业板"),
    Instrument(Symbol("601318.SH"), "中国平安", "上交所", "主板"),
    Instrument(Symbol("000333.SZ"), "美的集团", "深交所", "主板"),
)
_START_PRICES: Final = (1520.0, 142.0, 34.0, 186.0, 45.0, 52.0)
_WEEKEND_START: Final = 5
_MARKET_TIMEZONE: Final = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class DemoMarketDataProvider:
    """Generate stable, plausible data without representing real prices."""

    observation_count: int = 620

    @property
    def source_name(self) -> str:
        """Identify results that must not be treated as live market output."""
        return "demo"

    def list_instruments(self) -> tuple[Instrument, ...]:
        """Return the stable built-in research universe."""
        return _INSTRUMENTS

    def history(self, symbol: Symbol) -> tuple[MarketBar, ...]:
        """Return reproducible daily bars for a supported symbol."""
        instrument_index = next(
            (index for index, instrument in enumerate(_INSTRUMENTS) if instrument.symbol == symbol),
            None,
        )
        if instrument_index is None:
            msg = f"unknown demo symbol: {symbol}"
            raise LookupError(msg)
        return self._generate(symbol, instrument_index)

    def _generate(self, symbol: Symbol, seed: int) -> tuple[MarketBar, ...]:
        rng = np.random.default_rng(20260714 + seed * 97)
        dates = _business_dates(date(2024, 1, 2), self.observation_count)
        previous_close = _START_PRICES[seed]
        bars: list[MarketBar] = []
        for index, trading_date in enumerate(dates):
            cyclical = sin(index / (28.0 + seed * 3.0)) * 0.0022
            daily_return = 0.00018 + cyclical + float(rng.normal(0.0, 0.012 + seed * 0.0008))
            overnight = float(rng.normal(0.0, 0.0035))
            open_price = previous_close * (1.0 + overnight)
            close_price = max(previous_close * (1.0 + daily_return), 1.0)
            spread = abs(float(rng.normal(0.008, 0.003)))
            high = max(open_price, close_price) * (1.0 + spread)
            low = min(open_price, close_price) * (1.0 - spread)
            is_suspended = index > 0 and index % (181 + seed) == 0
            limit_rate = 0.2 if _INSTRUMENTS[seed].board == "创业板" else 0.1
            bars.append(
                MarketBar(
                    symbol=symbol,
                    trading_date=trading_date,
                    available_at=datetime.combine(
                        trading_date,
                        time(15, 5),
                        tzinfo=_MARKET_TIMEZONE,
                    ),
                    price_basis=PriceBasis.RAW,
                    open=round(open_price, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close_price, 2),
                    volume=int(rng.integers(3_000_000, 38_000_000)),
                    previous_close=round(previous_close, 2),
                    limit_up=round(previous_close * (1.0 + limit_rate), 2),
                    limit_down=round(previous_close * (1.0 - limit_rate), 2),
                    is_suspended=is_suspended,
                )
            )
            previous_close = close_price
        return tuple(bars)


def _business_dates(start: date, count: int) -> tuple[date, ...]:
    dates: list[date] = []
    current = start
    while len(dates) < count:
        if current.weekday() < _WEEKEND_START:
            dates.append(current)
        current += timedelta(days=1)
    return tuple(dates)
