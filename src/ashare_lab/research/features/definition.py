"""Versioned point-in-time feature metadata."""

from enum import StrEnum, unique
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@unique
class FeatureValueType(StrEnum):
    """Storage types allowed in the feature store."""

    FLOAT = "float"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class FeatureDefinition(BaseModel):
    """Auditable contract for one feature implementation."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    value_type: FeatureValueType
    lookback_trading_days: int = Field(ge=0)
    source_fields: tuple[str, ...] = Field(min_length=1)
    requires_available_at: Literal[True] = True
