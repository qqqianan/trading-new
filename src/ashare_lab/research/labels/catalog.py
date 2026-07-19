"""Closed first-version medium-horizon label definition."""

from ashare_lab.research.labels.definition import LabelDefinition


def medium_horizon_label() -> LabelDefinition:
    """Return the fixed t+1 open to t+21 open relative-return target."""
    return LabelDefinition(
        name="relative_open_return_20d_csi500",
        version="1.0.0",
        entry_lag_trading_days=1,
        holding_period_trading_days=20,
        benchmark_symbol="000905.SH",
    )
