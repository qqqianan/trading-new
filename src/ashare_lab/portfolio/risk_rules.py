"""Pure portfolio risk limit calculations used by the owning engine."""

from dataclasses import dataclass
from math import sqrt

from ashare_lab.domain.market import Symbol
from ashare_lab.domain.risk import RiskAction, RiskEvent, RiskRule
from ashare_lab.portfolio.risk_models import (
    PortfolioMarketSnapshot,
    PortfolioResearchStatus,
    PortfolioRiskConfig,
    PortfolioRiskRequest,
)


@dataclass(slots=True)
class PortfolioRiskState:
    """Mutable accumulator scoped to one risk assessment."""

    weights: dict[Symbol, float]
    scores: dict[Symbol, float]
    current: dict[Symbol, float]
    market: dict[Symbol, PortfolioMarketSnapshot]
    request: PortfolioRiskRequest
    config: PortfolioRiskConfig
    events: list[RiskEvent]


def limit_holdings(state: PortfolioRiskState) -> None:
    """Remove lowest-ranked positive targets above the holding limit."""
    positive = tuple(symbol for symbol, weight in state.weights.items() if weight > 0)
    if len(positive) <= state.config.maximum_positions:
        return
    ranked = sorted(positive, key=lambda symbol: (-state.scores[symbol], str(symbol)))
    keep = set(ranked[: state.config.maximum_positions])
    for symbol in positive:
        if symbol not in keep:
            state.weights[symbol] = 0.0
    state.events.append(
        RiskEvent(
            state.request.target.decision_date,
            RiskRule.MAX_HOLDINGS,
            RiskAction.REJECT,
            len(positive),
            state.config.maximum_positions,
            "positions above the ranked holding limit were removed",
        )
    )


def limit_positions(state: PortfolioRiskState) -> None:
    """Cap every target at the single-security limit."""
    for symbol, weight in tuple(state.weights.items()):
        if weight > state.config.max_position_weight:
            state.weights[symbol] = state.config.max_position_weight
            state.events.append(
                RiskEvent(
                    state.request.target.decision_date,
                    RiskRule.MAX_POSITION_WEIGHT,
                    RiskAction.RESIZE,
                    weight,
                    state.config.max_position_weight,
                    "target position was capped",
                    symbol,
                )
            )


def limit_new_risk(state: PortfolioRiskState) -> None:
    """Reject or resize increases using eligibility and board-lot capacity."""
    for symbol, target_weight in tuple(state.weights.items()):
        current_weight = state.current.get(symbol, 0.0)
        delta = target_weight - current_weight
        if delta <= 0:
            continue
        snapshot = state.market[symbol]
        if not snapshot.eligible_for_new_risk:
            state.weights[symbol] = current_weight
            state.events.append(
                RiskEvent(
                    state.request.target.decision_date,
                    RiskRule.NEW_RISK_INELIGIBLE,
                    RiskAction.REJECT,
                    delta,
                    0.0,
                    "new risk was rejected without forcing an exit",
                    symbol,
                )
            )
            continue
        requested_shares = delta * state.request.equity / snapshot.price
        capacity = snapshot.daily_volume * state.config.maximum_volume_participation
        liquid_lots = int(min(requested_shares, capacity) // snapshot.board_lot)
        if liquid_lots == 0:
            state.weights[symbol] = current_weight
            state.events.append(
                RiskEvent(
                    state.request.target.decision_date,
                    RiskRule.VOLUME_PARTICIPATION,
                    RiskAction.REJECT,
                    requested_shares,
                    capacity,
                    "increase is below one liquid board lot",
                    symbol,
                )
            )
            continue
        allowed_weight = liquid_lots * snapshot.board_lot * snapshot.price / state.request.equity
        if allowed_weight < delta:
            state.weights[symbol] = current_weight + allowed_weight
            state.events.append(
                RiskEvent(
                    state.request.target.decision_date,
                    RiskRule.VOLUME_PARTICIPATION,
                    RiskAction.RESIZE,
                    requested_shares,
                    capacity,
                    "increase was capped by liquid board-lot capacity",
                    symbol,
                )
            )


def limit_industries(state: PortfolioRiskState) -> PortfolioResearchStatus:
    """Resize known industry groups or block validation when PIT data is absent."""
    positive = tuple(symbol for symbol, weight in state.weights.items() if weight > 0)
    unknown = tuple(symbol for symbol in positive if state.market[symbol].industry is None)
    if unknown:
        state.events.append(
            RiskEvent(
                state.request.target.decision_date,
                RiskRule.INDUSTRY_EXPOSURE_UNAVAILABLE,
                RiskAction.BLOCK_VALIDATION,
                len(unknown),
                0.0,
                "PIT industry evidence is incomplete",
            )
        )
        return PortfolioResearchStatus.DRAFT
    industries: dict[str, list[Symbol]] = {}
    for symbol in positive:
        industry = state.market[symbol].industry
        if industry is not None:
            industries.setdefault(industry, []).append(symbol)
    for symbols in industries.values():
        exposure = sum(state.weights[symbol] for symbol in symbols)
        if exposure > state.config.maximum_industry_weight:
            scale = state.config.maximum_industry_weight / exposure
            for symbol in symbols:
                state.weights[symbol] *= scale
            state.events.append(
                RiskEvent(
                    state.request.target.decision_date,
                    RiskRule.MAX_INDUSTRY_WEIGHT,
                    RiskAction.RESIZE,
                    exposure,
                    state.config.maximum_industry_weight,
                    "industry exposure was proportionally resized",
                )
            )
    return PortfolioResearchStatus.VALIDATION_ELIGIBLE


def limit_gross_and_concentration(state: PortfolioRiskState) -> None:
    """Preserve minimum cash and cap Herfindahl concentration."""
    gross_limit = 1.0 - state.config.minimum_cash_weight
    gross = sum(state.weights.values())
    if gross > gross_limit:
        scale = gross_limit / gross
        for symbol in state.weights:
            state.weights[symbol] *= scale
        state.events.append(
            RiskEvent(
                state.request.target.decision_date,
                RiskRule.MINIMUM_CASH_WEIGHT,
                RiskAction.RESIZE,
                1.0 - gross,
                state.config.minimum_cash_weight,
                "stock gross was resized to preserve cash",
            )
        )
    concentration = sum(weight * weight for weight in state.weights.values())
    if concentration > state.config.maximum_concentration:
        scale = sqrt(state.config.maximum_concentration / concentration)
        for symbol in state.weights:
            state.weights[symbol] *= scale
        state.events.append(
            RiskEvent(
                state.request.target.decision_date,
                RiskRule.CONCENTRATION,
                RiskAction.RESIZE,
                concentration,
                state.config.maximum_concentration,
                "portfolio concentration was resized",
            )
        )


def limit_turnover(state: PortfolioRiskState) -> float:
    """Interpolate requested changes toward current holdings at the turnover cap."""
    symbols = set(state.weights) | set(state.current)
    raw = 0.5 * sum(
        abs(state.weights.get(symbol, 0.0) - state.current.get(symbol, 0.0)) for symbol in symbols
    )
    if raw <= state.config.maximum_turnover:
        return raw
    scale = state.config.maximum_turnover / raw
    for symbol in symbols:
        old_weight = state.current.get(symbol, 0.0)
        state.weights[symbol] = old_weight + (state.weights.get(symbol, 0.0) - old_weight) * scale
    state.events.append(
        RiskEvent(
            state.request.target.decision_date,
            RiskRule.MAX_TURNOVER,
            RiskAction.RESIZE,
            raw,
            state.config.maximum_turnover,
            "target changes were interpolated toward current holdings",
        )
    )
    return state.config.maximum_turnover
