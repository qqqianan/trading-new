"""Immutable provenance envelope for one portfolio backtest report."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.backtest.portfolio_contracts import PortfolioBacktestResult
from ashare_lab.backtest.portfolio_metrics import PortfolioPerformanceMetrics


class PortfolioBacktestReport(BaseModel):
    """Complete development result bound to targets, data, and frozen rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_artifact_id: str = Field(pattern=r"^portfolio_targets_[0-9a-f]{64}$")
    factor_report_id: str = Field(pattern=r"^factor_report_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    market_schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    benchmark_schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    source_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    benchmark_symbol: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    benchmark_price_basis: Literal["raw_open"]
    cost_rule_version: str = Field(min_length=1)
    risk_rule_version: str = Field(min_length=1)
    final_test_runs: int = Field(ge=0, le=0)
    result: PortfolioBacktestResult
    metrics: PortfolioPerformanceMetrics
