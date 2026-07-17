"""Daily long-only execution engine with core China A-share constraints."""

from dataclasses import dataclass, field
from datetime import date
from math import floor

from ashare_lab.backtest.costs import ChinaACommission
from ashare_lab.backtest.risk import RiskEngine, RiskLimits
from ashare_lab.domain.market import MarketBar
from ashare_lab.domain.risk import BuyRiskRequest, RiskAction, RiskEvent, RiskRule, RiskSnapshot
from ashare_lab.domain.trading import BacktestResult, EquityPoint, Trade, TradeSide
from ashare_lab.research.data_quality import DataQualityGuard


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Execution and capital assumptions for one backtest."""

    initial_cash: float
    allocation: float = 0.95
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage_rate: float = 0.0005
    board_lot: int = 100
    risk_limits: RiskLimits = field(default_factory=RiskLimits)


@dataclass(slots=True)
class _AccountState:
    """Mutable state owned exclusively by one engine run."""

    cash: float
    shares: int = 0
    acquired_on: date | None = None
    position_cost: float = 0.0
    total_fees: float = 0.0
    risk_halted: bool = False


class BacktestEngine:
    """Apply close-generated targets on the next eligible open."""

    def __init__(self, config: EngineConfig) -> None:
        """Create an isolated engine with immutable assumptions."""
        self._config = config
        self._cost_model = ChinaACommission(
            commission_rate=config.commission_rate,
            minimum_commission=config.minimum_commission,
            stamp_duty_rate=config.stamp_duty_rate,
        )
        self._risk_engine = RiskEngine(config.risk_limits)

    def run(self, bars: tuple[MarketBar, ...], targets: tuple[float, ...]) -> BacktestResult:
        """Simulate the target path over ordered daily bars."""
        data_quality = DataQualityGuard().validate(bars)
        if len(bars) != len(targets):
            msg = "bars and targets must have the same length"
            raise ValueError(msg)

        state = _AccountState(cash=self._config.initial_cash)
        trades: list[Trade] = []
        risk_events: list[RiskEvent] = []
        curve: list[EquityPoint] = []
        pending_target: float | None = None
        peak_equity = self._config.initial_cash

        for index, bar in enumerate(bars):
            if pending_target is not None:
                filled = self._try_execute(bar, pending_target, state, risk_events)
                if filled is not None:
                    trades.append(filled)
                    pending_target = None

            market_value = state.shares * bar.close
            equity = state.cash + market_value
            curve.append(
                EquityPoint(
                    trading_date=bar.trading_date,
                    equity=equity,
                    cash=state.cash,
                    market_value=market_value,
                )
            )
            previous_equity = curve[-2].equity if len(curve) > 1 else self._config.initial_cash
            peak_equity = max(peak_equity, equity)

            if index < len(bars) - 1:
                close_events = (
                    self._risk_engine.assess_close(
                        RiskSnapshot(
                            trading_date=bar.trading_date,
                            equity=equity,
                            peak_equity=peak_equity,
                            previous_equity=previous_equity,
                            position_market_value=market_value,
                            position_cost=state.position_cost,
                        )
                    )
                    if state.shares > 0 and not state.risk_halted
                    else ()
                )
                if close_events:
                    risk_events.extend(close_events)
                    state.risk_halted = True
                    pending_target = 0.0
                elif not state.risk_halted:
                    desired = targets[index]
                    is_invested = state.shares > 0
                    pending_target = desired if (desired > 0.0) != is_invested else None

        return BacktestResult(
            symbol=bars[0].symbol,
            initial_cash=self._config.initial_cash,
            ending_cash=state.cash,
            ending_shares=state.shares,
            total_fees=state.total_fees,
            data_quality=data_quality,
            risk_events=tuple(risk_events),
            trades=tuple(trades),
            equity_curve=tuple(curve),
        )

    def _try_execute(
        self,
        bar: MarketBar,
        target: float,
        state: _AccountState,
        risk_events: list[RiskEvent],
    ) -> Trade | None:
        if bar.is_suspended:
            self._record_blocked_exit(bar, state, risk_events, "suspension")
            return None
        if target > 0.0:
            return self._try_buy(bar, state, risk_events)
        return self._try_sell(bar, state, risk_events)

    def _try_buy(
        self,
        bar: MarketBar,
        state: _AccountState,
        risk_events: list[RiskEvent],
    ) -> Trade | None:
        if state.shares > 0 or bar.open >= bar.limit_up - 1e-8:
            return None
        price = bar.open * (1.0 + self._config.slippage_rate)
        budget = state.cash * self._config.allocation
        requested = floor(budget / price / self._config.board_lot) * self._config.board_lot
        decision = self._risk_engine.size_buy(
            BuyRiskRequest(
                trading_date=bar.trading_date,
                requested_quantity=requested,
                price=price,
                equity=state.cash,
                daily_volume=bar.volume,
                board_lot=self._config.board_lot,
            )
        )
        risk_events.extend(decision.events)
        quantity = decision.quantity
        if quantity <= 0:
            return None
        notional = quantity * price
        costs = self._cost_model.for_buy(notional)
        if notional + costs.total > state.cash:
            quantity -= self._config.board_lot
            notional = quantity * price
            costs = self._cost_model.for_buy(notional)
        if quantity <= 0:
            return None

        state.cash -= notional + costs.total
        state.shares = quantity
        state.acquired_on = bar.trading_date
        state.position_cost = notional + costs.total
        state.total_fees += costs.total
        return Trade(
            trading_date=bar.trading_date,
            symbol=bar.symbol,
            side=TradeSide.BUY,
            quantity=quantity,
            price=price,
            notional=notional,
            commission=costs.commission,
            stamp_duty=costs.stamp_duty,
            realized_pnl=None,
        )

    def _try_sell(
        self,
        bar: MarketBar,
        state: _AccountState,
        risk_events: list[RiskEvent],
    ) -> Trade | None:
        if state.shares <= 0 or state.acquired_on is None:
            return None
        if state.acquired_on >= bar.trading_date:
            return None
        if bar.open <= bar.limit_down + 1e-8:
            self._record_blocked_exit(bar, state, risk_events, "limit-down open")
            return None
        price = bar.open * (1.0 - self._config.slippage_rate)
        quantity = state.shares
        notional = quantity * price
        costs = self._cost_model.for_sell(notional)
        realized_pnl = notional - costs.total - state.position_cost
        state.cash += notional - costs.total
        state.shares = 0
        state.acquired_on = None
        state.position_cost = 0.0
        state.total_fees += costs.total
        return Trade(
            trading_date=bar.trading_date,
            symbol=bar.symbol,
            side=TradeSide.SELL,
            quantity=quantity,
            price=price,
            notional=notional,
            commission=costs.commission,
            stamp_duty=costs.stamp_duty,
            realized_pnl=realized_pnl,
        )

    @staticmethod
    def _record_blocked_exit(
        bar: MarketBar,
        state: _AccountState,
        risk_events: list[RiskEvent],
        reason: str,
    ) -> None:
        if not state.risk_halted or state.shares <= 0:
            return
        risk_events.append(
            RiskEvent(
                trading_date=bar.trading_date,
                rule=RiskRule.EXIT_BLOCKED,
                action=RiskAction.RETRY_EXIT,
                observed=bar.open,
                limit=bar.limit_down,
                message=f"risk exit blocked by {reason}; order retained",
            )
        )
