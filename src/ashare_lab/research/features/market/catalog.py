"""Closed first-version catalog for fifteen non-financial factors."""

from ashare_lab.research.features.definition import FeatureDefinition, FeatureValueType

_VERSION = "1.0.0"


def market_factor_catalog() -> tuple[FeatureDefinition, ...]:
    """Return fixed ordered definitions used by artifacts and DatasetSpec."""
    specs = (
        ("mom_20", 20, ("daily.close", "adj_factor.adj_factor")),
        ("mom_60", 60, ("daily.close", "adj_factor.adj_factor")),
        ("mom_120", 120, ("daily.close", "adj_factor.adj_factor")),
        ("reversal_5", 5, ("daily.close", "adj_factor.adj_factor")),
        ("vol_20", 20, ("daily.close", "adj_factor.adj_factor")),
        ("vol_60", 60, ("daily.close", "adj_factor.adj_factor")),
        ("max_drawdown_60", 60, ("daily.close", "adj_factor.adj_factor")),
        ("turnover_mean_20", 20, ("daily_basic.turnover_rate",)),
        ("amount_median_20", 20, ("daily.amount",)),
        ("amihud_20", 20, ("daily.close", "daily.pre_close", "daily.amount")),
        ("log_total_mv", 1, ("daily_basic.total_mv",)),
        ("earnings_yield_ttm", 1, ("daily_basic.pe_ttm",)),
        ("book_yield", 1, ("daily_basic.pb",)),
        ("sales_yield_ttm", 1, ("daily_basic.ps_ttm",)),
        ("dividend_yield_ttm", 1, ("daily_basic.dv_ttm",)),
    )
    return tuple(
        FeatureDefinition(
            name=name,
            version=_VERSION,
            description=f"Governed raw market factor: {name}",
            value_type=FeatureValueType.FLOAT,
            lookback_trading_days=lookback,
            source_fields=fields,
        )
        for name, lookback, fields in specs
    )
