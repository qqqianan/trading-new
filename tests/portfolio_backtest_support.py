from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Final

from ashare_lab.domain.market import MarketBar, PriceBasis, Symbol
from ashare_lab.portfolio import PortfolioMarketSnapshot, PortfolioTarget, TargetPosition

TRADING_DATES: Final[tuple[date, ...]] = (
    date(2024, 12, 27),
    date(2024, 12, 30),
    date(2024, 12, 31),
    date(2025, 1, 2),
    date(2025, 1, 3),
    date(2025, 1, 6),
)


def trading_date(day: int) -> date:
    return TRADING_DATES[day]


@dataclass(frozen=True, slots=True)
class BarOptions:
    volume: int = 1_000_000
    suspended: bool = False
    limit_up: bool = False
    limit_down: bool = False


DEFAULT_BAR_OPTIONS = BarOptions()


def bar(
    symbol: str,
    day: int,
    price: float,
    options: BarOptions = DEFAULT_BAR_OPTIONS,
) -> MarketBar:
    session_date = trading_date(day)
    return MarketBar(
        symbol=Symbol(symbol),
        trading_date=session_date,
        available_at=datetime.combine(session_date, time(15, 5), tzinfo=UTC),
        price_basis=PriceBasis.RAW,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=options.volume,
        previous_close=price,
        limit_up=price if options.limit_up else price * 1.1,
        limit_down=price if options.limit_down else price * 0.9,
        is_suspended=options.suspended,
    )


def target(day: int, positions: tuple[tuple[str, float], ...]) -> PortfolioTarget:
    return PortfolioTarget(
        decision_date=trading_date(day),
        model_id="factor_baseline_v1",
        positions=tuple(
            TargetPosition(Symbol(symbol), weight, float(len(positions) - index))
            for index, (symbol, weight) in enumerate(positions)
        ),
        cash_weight=1.0 - sum(weight for _, weight in positions),
    )


def market(
    symbols: tuple[str, ...],
    *,
    industry: str | None = "TECH",
) -> tuple[PortfolioMarketSnapshot, ...]:
    return tuple(
        PortfolioMarketSnapshot(
            symbol=Symbol(symbol),
            price=10.0,
            daily_volume=1_000_000,
            board_lot=100,
            industry=industry,
            eligible_for_new_risk=True,
        )
        for symbol in symbols
    )
