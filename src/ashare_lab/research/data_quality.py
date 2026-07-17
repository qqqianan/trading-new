"""Hard gates for temporal integrity and daily market data correctness."""

from datetime import date, datetime, time
from math import isfinite
from typing import Never

from ashare_lab.domain.market import MarketBar, PriceBasis
from ashare_lab.domain.quality import DataQualityReport

_NEXT_OPEN = time(9, 30)


class DataIntegrityError(Exception):
    """Market data violates a structural correctness rule."""

    __slots__ = ("detail", "index", "rule")

    def __init__(self, rule: str, index: int, detail: str) -> None:
        """Create a typed integrity failure while preserving traceback mutation."""
        super().__init__()
        self.rule = rule
        self.index = index
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable rule, location, and failure detail."""
        return f"{self.rule} at bar {self.index}: {self.detail}"


class TemporalLeakageError(Exception):
    """A datum became available after it would have influenced execution."""

    __slots__ = ("available_at", "next_execution_at", "trading_date")

    def __init__(
        self,
        trading_date: date,
        available_at: datetime,
        next_execution_at: datetime,
    ) -> None:
        """Create a typed point-in-time failure with execution context."""
        super().__init__()
        self.trading_date = trading_date
        self.available_at = available_at
        self.next_execution_at = next_execution_at

    def __str__(self) -> str:
        """Describe when the leaked observation actually became available."""
        return (
            f"bar {self.trading_date} became available at {self.available_at.isoformat()}, "
            f"after next execution time {self.next_execution_at.isoformat()}"
        )


class DataQualityGuard:
    """Reject invalid or temporally unavailable daily bars."""

    def validate(self, bars: tuple[MarketBar, ...]) -> DataQualityReport:
        """Run every hard data rule and return immutable evidence."""
        if not bars:
            _raise_integrity("non_empty", 0, "series contains no bars")

        expected_symbol = bars[0].symbol
        expected_basis = bars[0].price_basis
        for index, bar in enumerate(bars):
            if index < len(bars) - 1 and bars[index + 1].trading_date <= bar.trading_date:
                _raise_integrity(
                    "temporal_order",
                    index + 1,
                    "trading dates must be strictly increasing and unique",
                )
            self._validate_identity(bar, index, expected_symbol, expected_basis)
            self._validate_values(bar, index)
            if index < len(bars) - 1:
                self._validate_availability(bar, bars[index + 1])

        return DataQualityReport(
            passed=True,
            bar_count=len(bars),
            first_date=bars[0].trading_date,
            last_date=bars[-1].trading_date,
            price_basis=expected_basis,
            point_in_time=True,
            checks=(
                "identity_and_price_basis",
                "strict_temporal_order",
                "finite_positive_prices",
                "ohlc_geometry",
                "volume_and_limits",
                "available_before_next_open",
            ),
        )

    @staticmethod
    def _validate_identity(
        bar: MarketBar,
        index: int,
        expected_symbol: str,
        expected_basis: PriceBasis,
    ) -> None:
        if bar.symbol != expected_symbol:
            _raise_integrity("single_symbol", index, "symbol changes within series")
        if bar.price_basis is not expected_basis:
            _raise_integrity("single_price_basis", index, "price basis changes within series")
        if bar.available_at.tzinfo is None or bar.available_at.utcoffset() is None:
            _raise_integrity("timezone", index, "available_at must be timezone-aware")

    @staticmethod
    def _validate_values(bar: MarketBar, index: int) -> None:
        prices = (bar.open, bar.high, bar.low, bar.close, bar.previous_close)
        if not all(isfinite(price) and price > 0.0 for price in prices):
            _raise_integrity("price_domain", index, "prices must be finite and positive")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
            _raise_integrity("OHLC_geometry", index, "OHLC values are inconsistent")
        if bar.volume < 0:
            _raise_integrity("volume_domain", index, "volume cannot be negative")
        if not bar.limit_down < bar.limit_up:
            _raise_integrity("price_limits", index, "limit_down must be below limit_up")

    @staticmethod
    def _validate_availability(bar: MarketBar, next_bar: MarketBar) -> None:
        next_execution = datetime.combine(
            next_bar.trading_date,
            _NEXT_OPEN,
            tzinfo=bar.available_at.tzinfo,
        )
        if bar.available_at > next_execution:
            raise TemporalLeakageError(
                trading_date=bar.trading_date,
                available_at=bar.available_at,
                next_execution_at=next_execution,
            )


def _raise_integrity(rule: str, index: int, detail: str) -> Never:
    raise DataIntegrityError(rule, index, detail)
