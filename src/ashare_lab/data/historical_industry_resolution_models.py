"""Frozen deterministic source-resolution contracts for the industry pilot."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.historical_industry_source_models import (
    HistoricalIndustrySourceKind,
    HistoricalIndustrySourceObservation,
)


class HistoricalIndustryResolutionCount(BaseModel):
    """Stable count for one selected source branch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: HistoricalIndustrySourceKind
    count: int = Field(gt=0)


class HistoricalIndustryResolutionRow(BaseModel):
    """One preselected security and its uniquely resolved source chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    listing_date: date
    universe_event_ids: tuple[str, ...] = Field(min_length=1)
    universe_schema_manifest_id: str
    base_audit_id: str = Field(pattern=r"^cninfo_industry_bridge_audit_[0-9a-f]{64}$")
    evaluated_audit_ids: tuple[str, ...] = Field(min_length=1)
    selection_reason: str
    source: HistoricalIndustrySourceObservation


class HistoricalIndustryResolutionReport(BaseModel):
    """Content-addressed all-or-nothing source decision for one fixed selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution_id: str = Field(pattern=r"^historical_industry_resolution_[0-9a-f]{64}$")
    resolution_version: str
    resolved_at: datetime
    selection_id: str = Field(pattern=r"^cninfo_bridge_selection_[0-9a-f]{64}$")
    parent_base_batch_id: str = Field(pattern=r"^cninfo_bridge_batch_audit_[0-9a-f]{64}$")
    parent_supplemental_batch_id: str = Field(
        pattern=r"^cninfo_prospectus_bridge_batch_[0-9a-f]{64}$"
    )
    rows: tuple[HistoricalIndustryResolutionRow, ...] = Field(min_length=1)
    resolved_count: int = Field(gt=0)
    source_counts: tuple[HistoricalIndustryResolutionCount, ...]
    research_use_authorized: bool


class HistoricalIndustryResolutionError(Exception):
    """Pilot source inputs cannot produce one unique all-candidate decision."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one stable source-resolution failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the source-resolution boundary and concrete reason."""
        return f"historical_industry_resolution: {self.detail}"
