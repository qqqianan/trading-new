"""Portfolio close circuit-breaker assessment."""

from dataclasses import dataclass
from datetime import date

from ashare_lab.backtest.portfolio_account import PortfolioAccount
from ashare_lab.backtest.risk import RiskEngine
from ashare_lab.domain.risk import RiskEvent, RiskSnapshot


@dataclass(frozen=True, slots=True)
class CloseRiskContext:
    """One close mark evaluated against portfolio circuit limits."""

    trading_date: date
    equity: float
    peak: float
    previous: float
    market_value: float
    halted: bool


def assess_portfolio_close(
    engine: RiskEngine,
    account: PortfolioAccount,
    context: CloseRiskContext,
) -> tuple[RiskEvent, ...]:
    """Apply the existing circuit owner to aggregate portfolio state."""
    if not account.positions or context.halted:
        return ()
    position_cost = sum(item.total_cost for item in account.positions.values())
    return engine.assess_close(
        RiskSnapshot(
            context.trading_date,
            context.equity,
            context.peak,
            context.previous,
            context.market_value,
            position_cost,
        )
    )
