"""Closed first-version catalog for six PIT financial factors."""

from ashare_lab.research.features.definition import FeatureDefinition, FeatureValueType

_VERSION = "1.0.0"


def financial_factor_catalog() -> tuple[FeatureDefinition, ...]:
    """Return the fixed quality and growth factor definitions."""
    names = (
        "roe",
        "grossprofit_margin",
        "ocf_to_debt",
        "debt_to_assets",
        "q_sales_yoy",
        "q_netprofit_yoy",
    )
    return tuple(
        FeatureDefinition(
            name=name,
            version=_VERSION,
            description=f"Governed PIT financial factor: {name}",
            value_type=FeatureValueType.FLOAT,
            lookback_trading_days=0,
            source_fields=(f"pit_financial_indicators.{name}",),
        )
        for name in names
    )
