"""HTTP routes and boundary-to-domain mapping."""

from fastapi import APIRouter, HTTPException, status

from ashare_lab.api.schemas import (
    BacktestRequest,
    BacktestResponse,
    DataQualityResponse,
    EquityPointResponse,
    HealthResponse,
    MarketOverviewResponse,
    MarketPointResponse,
    MethodologyResponse,
    MetricsResponse,
    RiskEventResponse,
    RiskLimitsResponse,
    TradeResponse,
    WatchItemResponse,
)
from ashare_lab.domain.market import Symbol
from ashare_lab.domain.risk import RiskLimits
from ashare_lab.services.models import BacktestParameters, MarketOverview, ResearchResult
from ashare_lab.services.research import ResearchService

_DISCLAIMER = "仅供研究与软件验证; 演示行情并非真实市场数据, 不构成投资建议。"


def create_api_router(service: ResearchService) -> APIRouter:
    """Create API routes bound to one application service."""
    router = APIRouter(prefix="/api/v1")

    def health() -> HealthResponse:
        """Report service readiness and active data source."""
        return HealthResponse(status="ok", data_source=service.source_name)

    def market_overview() -> MarketOverviewResponse:
        """Return the latest dashboard market snapshot."""
        return _overview_response(service.overview())

    def run_backtest(payload: BacktestRequest) -> BacktestResponse:
        """Run one validated daily strategy simulation."""
        try:
            research = service.run_backtest(
                BacktestParameters(
                    symbol=Symbol(payload.symbol),
                    initial_cash=payload.initial_cash,
                    short_window=payload.short_window,
                    long_window=payload.long_window,
                    allocation=payload.allocation,
                    risk_limits=RiskLimits(
                        max_position_weight=payload.max_position_weight,
                        minimum_cash_weight=payload.minimum_cash_weight,
                        max_volume_participation=payload.max_volume_participation,
                        max_drawdown=payload.max_drawdown,
                        max_daily_loss=payload.max_daily_loss,
                        max_position_loss=payload.max_position_loss,
                    ),
                )
            )
        except LookupError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        return _backtest_response(research, payload)

    router.add_api_route("/health", health, methods=["GET"], tags=["system"])
    router.add_api_route(
        "/market/overview",
        market_overview,
        methods=["GET"],
        tags=["market"],
    )
    router.add_api_route("/backtests", run_backtest, methods=["POST"], tags=["research"])
    return router


def _overview_response(overview: MarketOverview) -> MarketOverviewResponse:
    return MarketOverviewResponse(
        data_source=overview.source_name,
        as_of_date=overview.as_of_date,
        advancing=overview.advancing,
        declining=overview.declining,
        unchanged=overview.unchanged,
        watchlist=tuple(
            WatchItemResponse(
                symbol=item.symbol,
                name=item.name,
                close=item.close,
                change_percent=item.change_percent,
                volume=item.volume,
            )
            for item in overview.watchlist
        ),
        market_curve=tuple(
            MarketPointResponse(trading_date=point.trading_date, value=point.value)
            for point in overview.market_curve
        ),
    )


def _backtest_response(
    research: ResearchResult,
    payload: BacktestRequest,
) -> BacktestResponse:
    metrics = research.metrics
    quality = research.result.data_quality
    limits = research.risk_limits
    return BacktestResponse(
        symbol=research.instrument.symbol,
        name=research.instrument.name,
        strategy=payload.strategy,
        data_source=research.source_name,
        disclaimer=_DISCLAIMER,
        methodology=MethodologyResponse(
            rulebook_version="1.1.0",
            research_status="demo_only",
            signal_timing="close_to_next_open",
            execution_price="next_tradable_open_with_slippage",
            transaction_costs_included=True,
            liquidity_control_enabled=True,
            risk_engine_enabled=True,
        ),
        data_quality=DataQualityResponse(
            passed=quality.passed,
            bar_count=quality.bar_count,
            first_date=quality.first_date,
            last_date=quality.last_date,
            price_basis=quality.price_basis,
            point_in_time=quality.point_in_time,
            checks=quality.checks,
        ),
        risk_limits=RiskLimitsResponse(
            max_position_weight=limits.max_position_weight,
            minimum_cash_weight=limits.minimum_cash_weight,
            max_volume_participation=limits.max_volume_participation,
            max_drawdown=limits.max_drawdown,
            max_daily_loss=limits.max_daily_loss,
            max_position_loss=limits.max_position_loss,
        ),
        risk_events=tuple(
            RiskEventResponse(
                trading_date=event.trading_date,
                rule=event.rule,
                action=event.action,
                observed=event.observed,
                limit=event.limit,
                message=event.message,
            )
            for event in research.result.risk_events
        ),
        metrics=MetricsResponse(
            total_return=metrics.total_return,
            annualized_return=metrics.annualized_return,
            annualized_volatility=metrics.annualized_volatility,
            sharpe_ratio=metrics.sharpe_ratio,
            max_drawdown=metrics.max_drawdown,
            win_rate=metrics.win_rate,
            trade_count=metrics.trade_count,
            total_fees=metrics.total_fees,
        ),
        equity_curve=tuple(
            EquityPointResponse(
                trading_date=point.trading_date,
                equity=point.equity,
                cash=point.cash,
                market_value=point.market_value,
            )
            for point in research.result.equity_curve
        ),
        trades=tuple(
            TradeResponse(
                trading_date=trade.trading_date,
                side=trade.side,
                quantity=trade.quantity,
                price=trade.price,
                notional=trade.notional,
                commission=trade.commission,
                stamp_duty=trade.stamp_duty,
                realized_pnl=trade.realized_pnl,
            )
            for trade in research.result.trades
        ),
    )
