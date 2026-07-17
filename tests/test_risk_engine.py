from datetime import date

from ashare_lab.backtest.risk import (
    RiskEngine,
    RiskLimits,
    RiskRule,
)
from ashare_lab.domain.risk import BuyRiskRequest


def test_pretrade_risk_caps_order_at_maximum_position_weight() -> None:
    # Given: a requested order larger than the allowed 50% position.
    engine = RiskEngine(
        RiskLimits(
            max_position_weight=0.5,
            minimum_cash_weight=0.05,
            max_volume_participation=1.0,
            max_drawdown=0.2,
            max_daily_loss=0.1,
            max_position_loss=0.15,
        )
    )

    # When: the buy is sized against CNY 100,000 equity at CNY 10.
    decision = engine.size_buy(
        BuyRiskRequest(
            trading_date=date(2025, 1, 2),
            requested_quantity=10_000,
            price=10.0,
            equity=100_000.0,
            daily_volume=1_000_000,
            board_lot=100,
        )
    )

    # Then: quantity is reduced to 5,000 shares and the binding rule is recorded.
    assert decision.quantity == 5_000
    assert decision.events[0].rule is RiskRule.MAX_POSITION_WEIGHT


def test_pretrade_risk_rejects_order_below_one_liquid_lot() -> None:
    # Given: volume participation permits fewer than 100 shares.
    engine = RiskEngine(RiskLimits(max_volume_participation=0.1))

    # When: a buy is sized on a 500-share volume day.
    decision = engine.size_buy(
        BuyRiskRequest(
            trading_date=date(2025, 1, 2),
            requested_quantity=1_000,
            price=10.0,
            equity=100_000.0,
            daily_volume=500,
            board_lot=100,
        )
    )

    # Then: the order is rejected and the liquidity rule is auditable.
    assert decision.quantity == 0
    assert decision.events[0].rule is RiskRule.VOLUME_PARTICIPATION
