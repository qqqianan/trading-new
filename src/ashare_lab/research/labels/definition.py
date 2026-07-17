"""Execution-aligned label metadata."""

from enum import StrEnum, unique

from pydantic import BaseModel, ConfigDict, Field


@unique
class LabelPrice(StrEnum):
    """Tradable price points supported by label construction."""

    OPEN = "open"
    CLOSE = "close"


class LabelDefinition(BaseModel):
    """Pinned future-return definition physically isolated from features."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    entry_lag_trading_days: int = Field(default=1, ge=1)
    holding_period_trading_days: int = Field(ge=1)
    entry_price: LabelPrice = LabelPrice.OPEN
    exit_price: LabelPrice = LabelPrice.OPEN
    benchmark_symbol: str = Field(min_length=1)
