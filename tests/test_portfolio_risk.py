from datetime import date

import pytest

from ashare_lab.domain.market import Symbol
from ashare_lab.domain.risk import RiskRule
from ashare_lab.portfolio.contracts import PortfolioTarget, TargetPosition
from ashare_lab.portfolio.risk import PortfolioRiskEngine, PortfolioRiskInputError
from ashare_lab.portfolio.risk_models import (
    CurrentPosition,
    PortfolioMarketSnapshot,
    PortfolioResearchStatus,
    PortfolioRiskConfig,
    PortfolioRiskRequest,
)


def _target(positions: tuple[tuple[str, float], ...]) -> PortfolioTarget:
    return PortfolioTarget(
        decision_date=date(2024, 12, 27),
        model_id="factor_baseline_v1",
        positions=tuple(
            TargetPosition(Symbol(symbol), weight=weight, score=1.0) for symbol, weight in positions
        ),
        cash_weight=1 - sum(weight for _, weight in positions),
    )


def _market(
    symbols: tuple[str, ...],
    *,
    daily_volume: int = 1_000_000,
    industry: str | None = "TECH",
    eligible: bool = True,
) -> tuple[PortfolioMarketSnapshot, ...]:
    return tuple(
        PortfolioMarketSnapshot(
            symbol=Symbol(symbol),
            price=10.0,
            daily_volume=daily_volume,
            board_lot=100,
            industry=industry,
            eligible_for_new_risk=eligible,
        )
        for symbol in symbols
    )


def test_portfolio_risk_rejects_buy_below_one_liquid_lot() -> None:
    # Given: a 3% target whose 5% volume allowance is below one board lot.
    target = _target((("000001.SZ", 0.03),))
    request = PortfolioRiskRequest(
        target=target,
        current_positions=(),
        market=_market(("000001.SZ",), daily_volume=500),
        equity=100_000.0,
    )

    # When: portfolio-level pre-trade risk is applied.
    decision = PortfolioRiskEngine(PortfolioRiskConfig()).assess(request)

    # Then: the target buy is rejected, audited, and cash remains conserved.
    assert decision.target.positions == ()
    assert decision.target.cash_weight == 1.0
    assert RiskRule.VOLUME_PARTICIPATION in {item.rule for item in decision.events}


def test_portfolio_risk_caps_turnover_without_losing_exit_intent() -> None:
    # Given: a full rotation from two current holdings into two new holdings.
    target = _target((("000003.SZ", 0.475), ("000004.SZ", 0.475)))
    current = (
        CurrentPosition(Symbol("000001.SZ"), weight=0.475),
        CurrentPosition(Symbol("000002.SZ"), weight=0.475),
    )
    symbols = ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ")
    config = PortfolioRiskConfig(
        max_position_weight=0.50,
        maximum_positions=30,
        minimum_cash_weight=0.05,
        maximum_turnover=0.25,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )

    # When: the turnover gate resizes the requested rotation.
    decision = PortfolioRiskEngine(config).assess(
        PortfolioRiskRequest(target, current, _market(symbols), equity=1_000_000.0)
    )

    # Then: turnover is capped and old symbols remain explicit reduction targets.
    assert decision.turnover == pytest.approx(0.25)
    assert RiskRule.MAX_TURNOVER in {item.rule for item in decision.events}
    assert {str(item.symbol) for item in decision.target.positions} == set(symbols)
    assert sum(
        item.weight for item in decision.target.positions
    ) + decision.target.cash_weight == pytest.approx(1.0)


def test_portfolio_risk_scales_known_industry_concentration() -> None:
    # Given: five 5% positions all assigned to one known PIT industry.
    symbols = tuple(f"00000{index}.SZ" for index in range(1, 6))
    target = _target(tuple((symbol, 0.05) for symbol in symbols))

    # When: the 20% industry limit is applied.
    decision = PortfolioRiskEngine(PortfolioRiskConfig()).assess(
        PortfolioRiskRequest(target, (), _market(symbols, industry="TECH"), 1_000_000.0)
    )

    # Then: the group is resized to 20% and the binding rule is disclosed.
    assert sum(item.weight for item in decision.target.positions) == pytest.approx(0.20)
    assert RiskRule.MAX_INDUSTRY_WEIGHT in {item.rule for item in decision.events}


def test_unknown_industry_blocks_validation_but_not_research_target() -> None:
    # Given: an otherwise feasible target without historical PIT industry evidence.
    target = _target((("000001.SZ", 0.03),))

    # When: portfolio risk assesses the unknown industry exposure.
    decision = PortfolioRiskEngine(PortfolioRiskConfig()).assess(
        PortfolioRiskRequest(
            target,
            (),
            _market(("000001.SZ",), industry=None),
            1_000_000.0,
        )
    )

    # Then: research continues as DRAFT and the missing gate is auditable.
    assert decision.status is PortfolioResearchStatus.DRAFT
    assert decision.target.positions[0].weight > 0
    assert RiskRule.INDUSTRY_EXPOSURE_UNAVAILABLE in {item.rule for item in decision.events}


def test_ineligible_new_risk_does_not_force_existing_position_sale() -> None:
    # Given: a held 3% position that the new target tries to increase to 5%.
    target = _target((("000001.SZ", 0.05),))
    current = (CurrentPosition(Symbol("000001.SZ"), 0.03),)

    # When: the symbol is no longer eligible for new risk.
    decision = PortfolioRiskEngine(PortfolioRiskConfig()).assess(
        PortfolioRiskRequest(
            target,
            current,
            _market(("000001.SZ",), eligible=False),
            1_000_000.0,
        )
    )

    # Then: the increase is rejected while the existing holding remains targeted.
    assert decision.target.positions[0].weight == pytest.approx(0.03)
    assert RiskRule.NEW_RISK_INELIGIBLE in {item.rule for item in decision.events}


def test_portfolio_risk_caps_holdings_position_and_concentration() -> None:
    # Given: three concentrated targets under a two-holding policy.
    symbols = ("000001.SZ", "000002.SZ", "000003.SZ")
    config = PortfolioRiskConfig(
        max_position_weight=0.04,
        maximum_positions=2,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=0.002,
    )

    # When: all position and concentration limits are applied.
    decision = PortfolioRiskEngine(config).assess(
        PortfolioRiskRequest(
            _target(tuple((symbol, 0.30) for symbol in symbols)),
            (),
            _market(symbols),
            1_000_000.0,
        )
    )

    # Then: only stable first two remain and every binding rule is audited.
    assert {str(item.symbol) for item in decision.target.positions} == set(symbols[:2])
    rules = {item.rule for item in decision.events}
    assert {RiskRule.MAX_HOLDINGS, RiskRule.MAX_POSITION_WEIGHT, RiskRule.CONCENTRATION} <= rules


def test_portfolio_risk_preserves_minimum_cash() -> None:
    # Given: an otherwise fully invested target.
    config = PortfolioRiskConfig(
        max_position_weight=1.0,
        maximum_positions=30,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=0.05,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    target = _target((("000001.SZ", 0.50), ("000002.SZ", 0.50)))
    market = _market(("000001.SZ", "000002.SZ"), daily_volume=100_000)

    # When: the minimum cash gate is applied.
    decision = PortfolioRiskEngine(config).assess(
        PortfolioRiskRequest(target, (), market, equity=100_000.0)
    )

    # Then: stock gross is capped and both decisions remain auditable.
    assert decision.target.cash_weight == pytest.approx(0.05)
    assert RiskRule.MINIMUM_CASH_WEIGHT in {item.rule for item in decision.events}


def test_portfolio_risk_resizes_increase_to_volume_capacity() -> None:
    # Given: capacity supports two lots but not the full requested increase.
    target = _target((("000001.SZ", 0.05),))

    # When: the 5% participation gate sizes the increase.
    decision = PortfolioRiskEngine(PortfolioRiskConfig()).assess(
        PortfolioRiskRequest(
            target,
            (),
            _market(("000001.SZ",), daily_volume=5_000),
            equity=100_000.0,
        )
    )

    # Then: the target is reduced to two board lots.
    assert decision.target.positions[0].weight == pytest.approx(0.02)
    assert RiskRule.VOLUME_PARTICIPATION in {item.rule for item in decision.events}


def test_portfolio_risk_rejects_invalid_policy() -> None:
    # Given: an invalid zero-turnover policy.
    invalid_config = PortfolioRiskConfig(maximum_turnover=0.0)

    # When / Then: invalid limits fail before an assessment can exist.
    with pytest.raises(PortfolioRiskInputError, match="risk limits"):
        PortfolioRiskEngine(invalid_config)


def test_portfolio_risk_rejects_missing_market_evidence() -> None:
    # Given: a target whose symbol has no PIT market evidence.
    request = PortfolioRiskRequest(_target((("000001.SZ", 0.03),)), (), (), 100_000.0)

    # When / Then: the request fails closed before sizing.
    with pytest.raises(PortfolioRiskInputError, match="market evidence"):
        PortfolioRiskEngine(PortfolioRiskConfig()).assess(request)
