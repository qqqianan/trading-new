"""Content-addressed weekly portfolio target research contracts."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class FrozenPortfolioModel(BaseModel):
    """Immutable trust-boundary model for portfolio research artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PortfolioTargetPositionRow(FrozenPortfolioModel):
    """One selected security's score and pre-risk target weight."""

    symbol: str = Field(pattern=r"^[0-9]{6}\.(SZ|SH|BJ)$")
    target_weight: float = Field(gt=0, lt=1, allow_inf_nan=False)
    score: float = Field(allow_inf_nan=False)


class PortfolioTargetRecord(FrozenPortfolioModel):
    """One weekly target that still requires portfolio risk and execution."""

    decision_date: date
    positions: tuple[PortfolioTargetPositionRow, ...] = Field(min_length=1)
    cash_weight: float = Field(ge=0, le=1, allow_inf_nan=False)


class PortfolioTargetBatch(FrozenPortfolioModel):
    """Complete development-only factor or model target artifact."""

    factor_report_id: str = Field(pattern=r"^factor_report_[0-9a-f]{64}$")
    model_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*_model_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    trial_batch_id: str = Field(pattern=r"^trial_batch_[0-9a-f]{64}$")
    portfolio_rule_version: str = Field(default="1.0.0", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    candidate_factor_names: tuple[str, ...] = Field(min_length=1)
    records: tuple[PortfolioTargetRecord, ...] = Field(min_length=1)
