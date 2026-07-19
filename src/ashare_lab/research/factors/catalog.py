"""Fixed first-version economic hypotheses for all twenty-one factors."""

from ashare_lab.research.factors.models import (
    ExpectedDirection,
    FactorFamily,
    FactorHypothesis,
)


def factor_hypotheses() -> tuple[FactorHypothesis, ...]:
    """Return the ordered hypotheses frozen before development diagnostics."""
    high = ExpectedDirection.HIGHER_IS_BETTER
    low = ExpectedDirection.LOWER_IS_BETTER
    specifications = (
        ("mom_20", FactorFamily.MOMENTUM, high, 0),
        ("mom_60", FactorFamily.MOMENTUM, high, 1),
        ("mom_120", FactorFamily.MOMENTUM, high, 2),
        ("reversal_5", FactorFamily.REVERSAL, low, 0),
        ("vol_20", FactorFamily.RISK, low, 0),
        ("vol_60", FactorFamily.RISK, low, 1),
        ("max_drawdown_60", FactorFamily.RISK, high, 2),
        ("turnover_mean_20", FactorFamily.LIQUIDITY, high, 2),
        ("amount_median_20", FactorFamily.LIQUIDITY, high, 0),
        ("amihud_20", FactorFamily.LIQUIDITY, low, 1),
        ("log_total_mv", FactorFamily.SIZE, low, 0),
        ("earnings_yield_ttm", FactorFamily.VALUE, high, 0),
        ("book_yield", FactorFamily.VALUE, high, 1),
        ("sales_yield_ttm", FactorFamily.VALUE, high, 2),
        ("dividend_yield_ttm", FactorFamily.VALUE, high, 3),
        ("roe", FactorFamily.QUALITY, high, 0),
        ("grossprofit_margin", FactorFamily.QUALITY, high, 1),
        ("ocf_to_debt", FactorFamily.QUALITY, high, 2),
        ("debt_to_assets", FactorFamily.QUALITY, low, 3),
        ("q_sales_yoy", FactorFamily.GROWTH, high, 1),
        ("q_netprofit_yoy", FactorFamily.GROWTH, high, 0),
    )
    return tuple(
        FactorHypothesis(
            feature_name=name,
            feature_version="1.0.0",
            family=family,
            expected_direction=direction,
            simplicity_rank=rank,
        )
        for name, family, direction, rank in specifications
    )
