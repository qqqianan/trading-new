"""Pure assembly of governed targets and market evidence for backtesting."""

from dataclasses import dataclass, replace
from datetime import date

from ashare_lab.backtest.portfolio_contracts import (
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.backtest.portfolio_metrics import BenchmarkPoint
from ashare_lab.domain.market import MarketBar, Symbol
from ashare_lab.portfolio import (
    PortfolioMarketSnapshot,
    PortfolioTarget,
    TargetPosition,
)
from ashare_lab.portfolio.research_models import (
    PortfolioTargetBatch,
    PortfolioTargetRecord,
)
from ashare_lab.research.features.market.mongo_contracts import MarketBundleReadResult
from ashare_lab.research.labels.models import BenchmarkOpenObservation


@dataclass(frozen=True, slots=True)
class PortfolioBacktestRunInputs:
    """Complete label-free inputs for one real development backtest."""

    sessions: tuple[PortfolioSession, ...]
    signals: tuple[PortfolioSignal, ...]
    benchmark: tuple[BenchmarkPoint, ...]


@dataclass(frozen=True, slots=True)
class PortfolioBacktestAssemblyError(Exception):
    """Targets and market evidence cannot form an unambiguous simulation."""

    detail: str

    def __str__(self) -> str:
        """Return the assembly boundary and concrete blocker."""
        return f"portfolio_backtest_assembly: {self.detail}"


def build_portfolio_backtest_inputs(
    batch: PortfolioTargetBatch,
    calendar: tuple[date, ...],
    market: MarketBundleReadResult,
    benchmark: tuple[BenchmarkOpenObservation, ...],
) -> PortfolioBacktestRunInputs:
    """Build raw daily sessions, PIT risk snapshots, and aligned benchmark points."""
    if market.rejections:
        detail = f"incomplete market bundle has {len(market.rejections)} rejected rows"
        raise PortfolioBacktestAssemblyError(detail)
    target_dates = tuple(item.decision_date for item in batch.records)
    if target_dates != tuple(sorted(set(target_dates))):
        detail = "portfolio target dates must be strictly increasing and unique"
        raise PortfolioBacktestAssemblyError(detail)
    if not calendar or set(target_dates) - set(calendar):
        detail = "portfolio target dates must belong to the governed calendar"
        raise PortfolioBacktestAssemblyError(detail)
    first_target = target_dates[0]
    sessions_dates = tuple(day for day in calendar if day >= first_target)
    bars_by_date = _bars_by_date(market, sessions_dates)
    suspended = set(market.suspended_keys)
    sessions = tuple(
        PortfolioSession(
            day,
            tuple(
                replace(bar, is_suspended=True) if (str(bar.symbol), day) in suspended else bar
                for bar in bars_by_date.get(day, ())
            ),
            tuple(
                Symbol(symbol)
                for symbol, suspended_day in market.suspended_keys
                if suspended_day == day
            ),
        )
        for day in sessions_dates
    )
    if any(not session.bars for session in sessions):
        detail = "every governed session must contain at least one target-union bar"
        raise PortfolioBacktestAssemblyError(detail)
    signals = _signals(batch, sessions_dates, bars_by_date, suspended)
    points = _benchmark_points(sessions_dates, benchmark)
    return PortfolioBacktestRunInputs(sessions, signals, points)


def _bars_by_date(
    market: MarketBundleReadResult,
    calendar: tuple[date, ...],
) -> dict[date, tuple[MarketBar, ...]]:
    allowed = set(calendar)
    values: dict[date, list[MarketBar]] = {}
    keys: set[tuple[date, Symbol]] = set()
    for observation in market.observations:
        bar = observation.bar
        if bar.trading_date not in allowed:
            continue
        key = (bar.trading_date, bar.symbol)
        if key in keys:
            detail = f"duplicate market bar: {bar.trading_date}:{bar.symbol}"
            raise PortfolioBacktestAssemblyError(detail)
        keys.add(key)
        values.setdefault(bar.trading_date, []).append(bar)
    return {
        day: tuple(sorted(bars, key=lambda item: str(item.symbol))) for day, bars in values.items()
    }


def _signals(
    batch: PortfolioTargetBatch,
    calendar: tuple[date, ...],
    bars_by_date: dict[date, tuple[MarketBar, ...]],
    suspended: set[tuple[str, date]],
) -> tuple[PortfolioSignal, ...]:
    targets = {item.decision_date: item for item in batch.records}
    latest: dict[Symbol, MarketBar] = {}
    seen: set[Symbol] = set()
    signals: list[PortfolioSignal] = []
    for day in calendar:
        daily = {bar.symbol: bar for bar in bars_by_date.get(day, ())}
        latest.update(daily)
        record = targets.get(day)
        if record is None:
            continue
        target_symbols = {Symbol(item.symbol) for item in record.positions}
        seen.update(target_symbols)
        missing = seen - latest.keys()
        if missing:
            detail = f"risk market history is absent for {len(missing)} target or holding symbols"
            raise PortfolioBacktestAssemblyError(detail)
        signals.append(
            PortfolioSignal(
                _target(batch, record),
                tuple(
                    PortfolioMarketSnapshot(
                        symbol,
                        latest[symbol].close,
                        daily[symbol].volume if symbol in daily else 0,
                        100,
                        None,
                        symbol in target_symbols
                        and symbol in daily
                        and (str(symbol), day) not in suspended,
                    )
                    for symbol in sorted(seen, key=str)
                ),
            )
        )
    return tuple(signals)


def _target(batch: PortfolioTargetBatch, record: PortfolioTargetRecord) -> PortfolioTarget:
    return PortfolioTarget(
        record.decision_date,
        batch.model_id or batch.factor_report_id,
        tuple(
            TargetPosition(Symbol(item.symbol), item.target_weight, item.score)
            for item in record.positions
        ),
        record.cash_weight,
    )


def _benchmark_points(
    calendar: tuple[date, ...],
    observations: tuple[BenchmarkOpenObservation, ...],
) -> tuple[BenchmarkPoint, ...]:
    values = {item.trading_date: item.open_price for item in observations}
    if len(values) != len(observations) or set(calendar) != set(values):
        detail = "benchmark observations must exactly match governed sessions"
        raise PortfolioBacktestAssemblyError(detail)
    return tuple(BenchmarkPoint(day, values[day]) for day in calendar)
