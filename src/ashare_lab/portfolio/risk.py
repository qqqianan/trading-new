"""Portfolio-level pre-trade risk sizing without execution authority."""

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from ashare_lab.domain.market import Symbol
from ashare_lab.portfolio.contracts import PortfolioTarget, TargetPosition
from ashare_lab.portfolio.risk_models import (
    PortfolioMarketSnapshot,
    PortfolioRiskConfig,
    PortfolioRiskDecision,
    PortfolioRiskRequest,
)
from ashare_lab.portfolio.risk_rules import (
    PortfolioRiskState,
    limit_gross_and_concentration,
    limit_holdings,
    limit_industries,
    limit_new_risk,
    limit_positions,
    limit_turnover,
)

if TYPE_CHECKING:
    from ashare_lab.domain.risk import RiskEvent


@dataclass(frozen=True, slots=True)
class PortfolioRiskInputError(Exception):
    """Portfolio risk input violates the internal typed contract."""

    detail: str

    def __str__(self) -> str:
        """Return the risk boundary and concrete contract failure."""
        return f"portfolio_risk_input: {self.detail}"


class PortfolioRiskEngine:
    """Own all portfolio resizing and rejection before execution simulation."""

    def __init__(self, config: PortfolioRiskConfig) -> None:
        """Bind and validate one immutable portfolio risk policy."""
        limits = (
            config.max_position_weight,
            config.minimum_cash_weight,
            config.maximum_turnover,
            config.maximum_volume_participation,
            config.maximum_industry_weight,
            config.maximum_concentration,
        )
        if (
            any(not isfinite(value) or value <= 0 or value > 1 for value in limits)
            or config.maximum_positions <= 0
        ):
            detail = "risk limits must be finite and within (0, 1]"
            raise PortfolioRiskInputError(detail)
        self._config = config

    def assess(self, request: PortfolioRiskRequest) -> PortfolioRiskDecision:
        """Return a governed target and every binding risk decision."""
        current, market = _validate_request(request)
        weights = {item.symbol: item.weight for item in request.target.positions}
        scores = {item.symbol: item.score for item in request.target.positions}
        for symbol in current:
            weights.setdefault(symbol, 0.0)
            scores.setdefault(symbol, 0.0)
        events: list[RiskEvent] = []
        state = PortfolioRiskState(weights, scores, current, market, request, self._config, events)
        limit_holdings(state)
        limit_positions(state)
        limit_new_risk(state)
        status = limit_industries(state)
        limit_gross_and_concentration(state)
        turnover = limit_turnover(state)
        concentration = sum(weight * weight for weight in weights.values() if weight > 0)
        positions = tuple(
            TargetPosition(symbol, weight, scores[symbol])
            for symbol, weight in sorted(weights.items(), key=lambda item: str(item[0]))
            if weight > 0 or symbol in current
        )
        gross = sum(item.weight for item in positions)
        return PortfolioRiskDecision(
            target=PortfolioTarget(
                decision_date=request.target.decision_date,
                model_id=request.target.model_id,
                positions=positions,
                cash_weight=1.0 - gross,
            ),
            events=tuple(events),
            turnover=turnover,
            concentration=concentration,
            status=status,
        )


def _validate_request(
    request: PortfolioRiskRequest,
) -> tuple[dict[Symbol, float], dict[Symbol, PortfolioMarketSnapshot]]:
    if not isfinite(request.equity) or request.equity <= 0:
        detail = "equity must be finite and positive"
        raise PortfolioRiskInputError(detail)
    target_symbols = tuple(item.symbol for item in request.target.positions)
    current_symbols = tuple(item.symbol for item in request.current_positions)
    market_symbols = tuple(item.symbol for item in request.market)
    if any(
        len(items) != len(set(items)) for items in (target_symbols, current_symbols, market_symbols)
    ):
        detail = "symbols must be unique within each input"
        raise PortfolioRiskInputError(detail)
    if any(not isfinite(item.weight) or item.weight < 0 for item in request.target.positions):
        detail = "target weights must be finite and non-negative"
        raise PortfolioRiskInputError(detail)
    if any(not isfinite(item.weight) or item.weight < 0 for item in request.current_positions):
        detail = "current weights must be finite and non-negative"
        raise PortfolioRiskInputError(detail)
    current = {item.symbol: item.weight for item in request.current_positions}
    market = {item.symbol: item for item in request.market}
    required = set(target_symbols) | set(current_symbols)
    if required - market.keys():
        detail = "market evidence is required for every target and holding"
        raise PortfolioRiskInputError(detail)
    if any(
        not isfinite(item.price) or item.price <= 0 or item.daily_volume < 0 or item.board_lot <= 0
        for item in request.market
    ):
        detail = "market prices, volume, and board lots must be valid"
        raise PortfolioRiskInputError(detail)
    return current, market
