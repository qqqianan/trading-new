from datetime import UTC, date, datetime, time, timedelta

from ashare_lab.domain.market import MarketBar, PriceBasis, Symbol
from ashare_lab.strategies.moving_average import MovingAverageCross


def _bars(closes: list[float]) -> tuple[MarketBar, ...]:
    start = date(2025, 1, 2)
    return tuple(
        MarketBar(
            symbol=Symbol("600000.SH"),
            trading_date=start + timedelta(days=index),
            available_at=datetime.combine(
                start + timedelta(days=index),
                time(15, 5),
                tzinfo=UTC,
            ),
            price_basis=PriceBasis.RAW,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000_000,
            previous_close=closes[max(0, index - 1)],
            limit_up=close * 1.1,
            limit_down=close * 0.9,
            is_suspended=False,
        )
        for index, close in enumerate(closes)
    )


def test_moving_average_enters_only_after_long_window_is_available() -> None:
    # Given: prices with a bullish short average after five observations.
    strategy = MovingAverageCross(short_window=2, long_window=5)

    # When: target positions are generated.
    targets = strategy.targets(_bars([10.0, 10.0, 10.0, 11.0, 12.0]))

    # Then: early observations stay flat and the fifth close turns long.
    assert targets == (0.0, 0.0, 0.0, 0.0, 1.0)
