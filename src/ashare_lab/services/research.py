"""Orchestrate data, strategy, execution, and analytics."""

from ashare_lab.backtest.engine import BacktestEngine, EngineConfig
from ashare_lab.backtest.metrics import calculate_metrics
from ashare_lab.domain.market import MarketDataProvider
from ashare_lab.research.data_quality import DataQualityGuard
from ashare_lab.services.models import (
    BacktestParameters,
    MarketOverview,
    MarketPoint,
    ResearchResult,
    WatchItem,
)
from ashare_lab.strategies.moving_average import MovingAverageCross


class ResearchService:
    """Application facade for the local research workbench."""

    def __init__(self, provider: MarketDataProvider) -> None:
        """Bind the use cases to one market data provider."""
        self._provider = provider

    @property
    def source_name(self) -> str:
        """Expose the active provider at the API boundary."""
        return self._provider.source_name

    def run_backtest(self, parameters: BacktestParameters) -> ResearchResult:
        """Run the transparent baseline strategy with A-share execution."""
        instruments = self._provider.list_instruments()
        instrument = next(
            (item for item in instruments if item.symbol == parameters.symbol),
            None,
        )
        if instrument is None:
            msg = f"unknown symbol: {parameters.symbol}"
            raise LookupError(msg)
        bars = self._provider.history(parameters.symbol)
        DataQualityGuard().validate(bars)
        strategy = MovingAverageCross(
            short_window=parameters.short_window,
            long_window=parameters.long_window,
        )
        targets = strategy.targets(bars)
        engine = BacktestEngine(
            EngineConfig(
                initial_cash=parameters.initial_cash,
                allocation=parameters.allocation,
                risk_limits=parameters.risk_limits,
            )
        )
        result = engine.run(bars, targets)
        return ResearchResult(
            instrument=instrument,
            source_name=self._provider.source_name,
            result=result,
            metrics=calculate_metrics(result),
            risk_limits=parameters.risk_limits,
        )

    def overview(self) -> MarketOverview:
        """Build a compact equal-weight market and watchlist snapshot."""
        instruments = self._provider.list_instruments()
        histories = tuple(self._provider.history(instrument.symbol) for instrument in instruments)
        watchlist = tuple(
            WatchItem(
                symbol=instrument.symbol,
                name=instrument.name,
                close=bars[-1].close,
                change_percent=(bars[-1].close / bars[-2].close - 1.0),
                volume=bars[-1].volume,
            )
            for instrument, bars in zip(instruments, histories, strict=True)
        )
        changes = [item.change_percent for item in watchlist]
        curve_length = 90
        market_curve = tuple(
            MarketPoint(
                trading_date=histories[0][-curve_length + index].trading_date,
                value=sum(
                    bars[-curve_length + index].close / bars[-curve_length].close
                    for bars in histories
                )
                / len(histories)
                * 100.0,
            )
            for index in range(curve_length)
        )
        return MarketOverview(
            source_name=self._provider.source_name,
            as_of_date=histories[0][-1].trading_date,
            watchlist=watchlist,
            market_curve=market_curve,
            advancing=sum(1 for change in changes if change > 0.0),
            declining=sum(1 for change in changes if change < 0.0),
            unchanged=sum(1 for change in changes if change == 0.0),
        )
