"""Frozen coverage decision contracts for historical-industry admissions."""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HistoricalIndustryCoverageDecision(StrEnum):
    """Closed decision before any research-data publication is implemented."""

    BLOCKED = "BLOCKED"
    READY_FOR_RESEARCH_ADMISSION_REVIEW = "READY_FOR_RESEARCH_ADMISSION_REVIEW"


class HistoricalIndustryUnknownInterval(BaseModel):
    """One source-unavailable interval overlapping the requested research window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    unknown_from: datetime
    unknown_until: datetime


class HistoricalIndustryCoverageReport(BaseModel):
    """Content-addressed population, conflict, and PIT completeness decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str = Field(pattern=r"^historical_industry_coverage_[0-9a-f]{64}$")
    report_version: str
    evaluated_at: datetime
    selection_id: str = Field(pattern=r"^cninfo_bridge_selection_[0-9a-f]{64}$")
    resolution_id: str = Field(pattern=r"^historical_industry_resolution_[0-9a-f]{64}$")
    admission_batch_id: str = Field(pattern=r"^historical_industry_admission_batch_[0-9a-f]{64}$")
    candidate_universe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_start: datetime
    coverage_end_exclusive: datetime
    population_count: int = Field(gt=0)
    selected_count: int = Field(gt=0)
    admitted_selected_count: int = Field(ge=0)
    population_missing_count: int = Field(ge=0)
    missing_selected_symbols: tuple[str, ...]
    unexpected_admission_symbols: tuple[str, ...]
    duplicate_admission_symbols: tuple[str, ...]
    conflicting_admission_symbols: tuple[str, ...]
    lineage_mismatch_symbols: tuple[str, ...]
    unknown_intervals: tuple[HistoricalIndustryUnknownInterval, ...]
    blocking_reasons: tuple[str, ...]
    decision: HistoricalIndustryCoverageDecision
    research_use_authorized: bool

    @model_validator(mode="after")
    def decision_matches_evidence(self) -> Self:
        """Prevent serialized reports from enabling research use or hiding blockers."""
        ready = (
            self.decision is HistoricalIndustryCoverageDecision.READY_FOR_RESEARCH_ADMISSION_REVIEW
        )
        if self.research_use_authorized or ready == bool(self.blocking_reasons):
            message = "coverage decision, blockers, or research authority differ"
            raise ValueError(message)
        return self


class HistoricalIndustryCoverageError(Exception):
    """Exact source-only parents cannot form one coverage decision."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record a stable fail-closed coverage failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the coverage boundary and concrete reason."""
        return f"historical_industry_coverage: {self.detail}"
