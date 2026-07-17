from ashare_lab.backtest.costs import ChinaACommission


def test_buy_commission_uses_minimum_fee_when_rate_fee_is_lower() -> None:
    # Given: a small buy whose proportional commission is below CNY 5.
    model = ChinaACommission(commission_rate=0.0003, minimum_commission=5.0, stamp_duty_rate=0.0005)

    # When: costs are calculated for a CNY 10,000 buy.
    costs = model.for_buy(10_000.0)

    # Then: minimum commission applies and no stamp duty is charged.
    assert costs.commission == 5.0
    assert costs.stamp_duty == 0.0
    assert costs.total == 5.0


def test_sell_cost_includes_commission_and_stamp_duty() -> None:
    # Given: a sell with proportional commission above the minimum.
    model = ChinaACommission(commission_rate=0.0003, minimum_commission=5.0, stamp_duty_rate=0.0005)

    # When: costs are calculated for a CNY 100,000 sell.
    costs = model.for_sell(100_000.0)

    # Then: both commission and sell-side stamp duty are charged.
    assert costs.commission == 30.0
    assert costs.stamp_duty == 50.0
    assert costs.total == 80.0
