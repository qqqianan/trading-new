"""Pydantic request and response contracts."""

from datetime import date
from enum import StrEnum, unique
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    """Immutable API model base."""

    model_config = ConfigDict(frozen=True)


@unique
class StrategyName(StrEnum):
    """Publicly supported strategies."""

    MOVING_AVERAGE_CROSS = "moving_average_cross"


class HealthResponse(FrozenModel):
    """Readiness payload."""

    status: str
    data_source: str


class BacktestRequest(FrozenModel):
    """User-controlled backtest configuration."""

    symbol: str = Field(pattern=r"^\d{6}\.(SH|SZ)$")
    strategy: StrategyName = StrategyName.MOVING_AVERAGE_CROSS
    initial_cash: float = Field(default=1_000_000.0, ge=10_000.0, le=100_000_000.0)
    short_window: int = Field(default=10, ge=2, le=120)
    long_window: int = Field(default=30, ge=5, le=250)
    allocation: float = Field(default=0.95, ge=0.1, le=1.0)
    max_position_weight: float = Field(default=0.95, ge=0.05, le=1.0)
    minimum_cash_weight: float = Field(default=0.05, ge=0.0, le=0.5)
    max_volume_participation: float = Field(default=0.10, ge=0.001, le=1.0)
    max_drawdown: float = Field(default=0.20, ge=0.03, le=0.8)
    max_daily_loss: float = Field(default=0.08, ge=0.01, le=0.5)
    max_position_loss: float = Field(default=0.15, ge=0.02, le=0.8)

    @model_validator(mode="after")
    def validate_windows(self) -> Self:
        """Require a genuinely shorter fast average."""
        if self.short_window >= self.long_window:
            msg = "short_window must be lower than long_window"
            raise ValueError(msg)
        return self


class MetricsResponse(FrozenModel):
    """Net performance and risk metrics."""

    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    total_fees: float


class EquityPointResponse(FrozenModel):
    """One daily equity observation."""

    trading_date: date
    equity: float
    cash: float
    market_value: float


class TradeResponse(FrozenModel):
    """One completed simulated fill."""

    trading_date: date
    side: str
    quantity: int
    price: float
    notional: float
    commission: float
    stamp_duty: float
    realized_pnl: float | None


class DataQualityResponse(FrozenModel):
    """Evidence that data passed the non-bypassable research gate."""

    passed: bool
    bar_count: int
    first_date: date
    last_date: date
    price_basis: str
    point_in_time: bool
    checks: tuple[str, ...]


class MethodologyResponse(FrozenModel):
    """Backtest timing and governance assumptions."""

    rulebook_version: str
    research_status: str
    signal_timing: str
    execution_price: str
    transaction_costs_included: bool
    liquidity_control_enabled: bool
    risk_engine_enabled: bool


class RiskLimitsResponse(FrozenModel):
    """Risk policy used for the reported simulation."""

    max_position_weight: float
    minimum_cash_weight: float
    max_volume_participation: float
    max_drawdown: float
    max_daily_loss: float
    max_position_loss: float


class RiskEventResponse(FrozenModel):
    """One pre-trade adjustment or portfolio circuit-breaker event."""

    trading_date: date
    rule: str
    action: str
    observed: float
    limit: float
    message: str


class BacktestResponse(FrozenModel):
    """Complete inspectable research result."""

    symbol: str
    name: str
    strategy: StrategyName
    data_source: str
    disclaimer: str
    methodology: MethodologyResponse
    data_quality: DataQualityResponse
    risk_limits: RiskLimitsResponse
    risk_events: tuple[RiskEventResponse, ...]
    metrics: MetricsResponse
    equity_curve: tuple[EquityPointResponse, ...]
    trades: tuple[TradeResponse, ...]


class WatchItemResponse(FrozenModel):
    """Latest watchlist observation."""

    symbol: str
    name: str
    close: float
    change_percent: float
    volume: int


class MarketPointResponse(FrozenModel):
    """Normalized equal-weight market observation."""

    trading_date: date
    value: float


class MarketOverviewResponse(FrozenModel):
    """Dashboard overview response."""

    data_source: str
    as_of_date: date
    advancing: int
    declining: int
    unchanged: int
    watchlist: tuple[WatchItemResponse, ...]
    market_curve: tuple[MarketPointResponse, ...]
