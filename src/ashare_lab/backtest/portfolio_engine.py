"""Governed multi-asset A-share portfolio backtest orchestration."""

from dataclasses import dataclass, field
from math import isfinite
from typing import TYPE_CHECKING

from ashare_lab.backtest.costs import ChinaACommission
from ashare_lab.backtest.portfolio_account import PortfolioAccount
from ashare_lab.backtest.portfolio_close_risk import CloseRiskContext, assess_portfolio_close
from ashare_lab.backtest.portfolio_contracts import (
    OrderBlockReason,
    OrderStatus,
    PortfolioBacktestInputError,
    PortfolioBacktestResult,
    PortfolioEquityPoint,
    PortfolioExecutionAssumptions,
    PortfolioOrderRecord,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.backtest.portfolio_execution import BOARD_LOT, ExecutionPolicy, ExecutionRequest
from ashare_lab.backtest.portfolio_validation import validate_portfolio_inputs
from ashare_lab.backtest.risk import RiskEngine
from ashare_lab.domain.risk import RiskEvent, RiskLimits
from ashare_lab.portfolio import (
    CurrentPosition,
    PortfolioResearchStatus,
    PortfolioRiskConfig,
    PortfolioRiskDecision,
    PortfolioRiskEngine,
    PortfolioRiskRequest,
)

if TYPE_CHECKING:
    from ashare_lab.domain.market import Symbol
    from ashare_lab.domain.trading import Trade


@dataclass(frozen=True, slots=True)
class PortfolioBacktestConfig:
    """Frozen execution, cost, portfolio, and circuit-breaker assumptions."""

    initial_cash: float
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage_rate: float = 0.0005
    portfolio_risk: PortfolioRiskConfig = field(default_factory=PortfolioRiskConfig)
    circuit_limits: RiskLimits = field(default_factory=RiskLimits)


class PortfolioBacktestEngine:
    """Run close target, risk, next-open execution, and close mark in order."""

    def __init__(self, config: PortfolioBacktestConfig) -> None:
        """Create isolated execution and risk owners for one run."""
        if not isfinite(config.initial_cash) or config.initial_cash <= 0:
            detail = "initial cash must be finite and positive"
            raise PortfolioBacktestInputError(detail)
        costs = (
            config.commission_rate,
            config.minimum_commission,
            config.stamp_duty_rate,
            config.slippage_rate,
        )
        if any(not isfinite(value) or value < 0 for value in costs) or config.slippage_rate >= 1:
            detail = "cost and slippage assumptions must be finite and non-negative"
            raise PortfolioBacktestInputError(detail)
        circuit = config.circuit_limits
        circuit_values = (
            circuit.max_position_weight,
            circuit.minimum_cash_weight,
            circuit.max_volume_participation,
            circuit.max_drawdown,
            circuit.max_daily_loss,
            circuit.max_position_loss,
        )
        if any(not isfinite(value) or value <= 0 or value > 1 for value in circuit_values):
            detail = "circuit limits must be finite and within (0, 1]"
            raise PortfolioBacktestInputError(detail)
        self._config = config
        self._portfolio_risk = PortfolioRiskEngine(config.portfolio_risk)
        self._circuit_risk = RiskEngine(config.circuit_limits)
        self._costs = ChinaACommission(
            config.commission_rate,
            config.minimum_commission,
            config.stamp_duty_rate,
        )
        self._execution_policy = ExecutionPolicy(
            config.portfolio_risk.maximum_volume_participation,
            config.slippage_rate,
            config.portfolio_risk.minimum_cash_weight,
            self._costs,
        )

    def run(
        self,
        sessions: tuple[PortfolioSession, ...],
        signals: tuple[PortfolioSignal, ...],
    ) -> PortfolioBacktestResult:
        """Simulate ordered sessions after mandatory data and portfolio risk gates."""
        quality = validate_portfolio_inputs(sessions, signals)
        signal_by_date = {item.target.decision_date: item for item in signals}
        account = PortfolioAccount(self._config.initial_cash)
        trades: list[Trade] = []
        orders: list[PortfolioOrderRecord] = []
        risk_events: list[RiskEvent] = []
        decisions: list[PortfolioRiskDecision] = []
        curve: list[PortfolioEquityPoint] = []
        pending: dict[Symbol, float] | None = None
        pending_risk_exit = False
        halted = False
        peak = self._config.initial_cash
        research_status = PortfolioResearchStatus.VALIDATION_ELIGIBLE

        for session in sessions:
            if pending is not None:
                batch = account.execute(
                    ExecutionRequest(
                        session,
                        pending,
                        self._execution_policy,
                        pending_risk_exit,
                    )
                )
                trades.extend(batch.trades)
                orders.extend(batch.orders)
                risk_events.extend(batch.risk_events)
                if not batch.has_pending:
                    pending = None
                    pending_risk_exit = False

            market_value, equity = account.mark(session)
            previous = curve[-1].equity if curve else self._config.initial_cash
            peak = max(peak, equity)
            curve.append(
                PortfolioEquityPoint(session.trading_date, equity, account.cash, market_value)
            )

            close_events = assess_portfolio_close(
                self._circuit_risk,
                account,
                CloseRiskContext(
                    session.trading_date,
                    equity,
                    peak,
                    previous,
                    market_value,
                    halted,
                ),
            )
            if close_events:
                risk_events.extend(close_events)
                halted = True
                pending = dict.fromkeys(account.positions, 0.0)
                pending_risk_exit = True
                continue

            signal = signal_by_date.get(session.trading_date)
            if signal is None or halted:
                continue
            decision = self._portfolio_risk.assess(
                PortfolioRiskRequest(
                    signal.target,
                    tuple(
                        CurrentPosition(symbol, weight)
                        for symbol, weight in account.weights(equity).items()
                    ),
                    signal.market,
                    equity,
                )
            )
            decisions.append(decision)
            risk_events.extend(decision.events)
            if decision.status is PortfolioResearchStatus.DRAFT:
                research_status = PortfolioResearchStatus.DRAFT
            pending = {item.symbol: item.weight for item in decision.target.positions}
            pending_risk_exit = False

        return PortfolioBacktestResult(
            initial_cash=self._config.initial_cash,
            ending_cash=account.cash,
            execution_assumptions=PortfolioExecutionAssumptions(
                commission_rate=self._config.commission_rate,
                minimum_commission=self._config.minimum_commission,
                stamp_duty_rate=self._config.stamp_duty_rate,
                slippage_rate=self._config.slippage_rate,
                board_lot=BOARD_LOT,
            ),
            portfolio_risk_config=self._config.portfolio_risk,
            circuit_limits=self._config.circuit_limits,
            positions=account.snapshots(),
            total_fees=account.total_fees,
            data_quality=quality,
            risk_events=tuple(risk_events),
            risk_decisions=tuple(decisions),
            orders=tuple(orders),
            trades=tuple(trades),
            equity_curve=tuple(curve),
            research_status=research_status,
        )


__all__ = [
    "OrderBlockReason",
    "OrderStatus",
    "PortfolioBacktestConfig",
    "PortfolioBacktestEngine",
    "PortfolioSession",
    "PortfolioSignal",
]
