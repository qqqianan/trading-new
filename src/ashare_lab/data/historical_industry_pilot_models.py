"""Frozen unified admission and batch contracts for the fixed industry pilot."""

from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.data.historical_industry_admission_models import (
    HistoricalIndustryQualityStatus,
)
from ashare_lab.data.historical_industry_source_models import (
    HistoricalIndustrySourceObservation,
)


class PilotIndustryRawObservation(BaseModel):
    """Resolved source row retained as an immutable source-only Raw payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_id: str = Field(pattern=r"^historical_industry_pilot_raw_[0-9a-f]{64}$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    resolution_id: str = Field(pattern=r"^historical_industry_resolution_[0-9a-f]{64}$")
    source: HistoricalIndustrySourceObservation


class PilotIndustryQualityReport(BaseModel):
    """Source-only quality decision for one resolved pilot row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quality_report_id: str = Field(pattern=r"^historical_industry_pilot_quality_[0-9a-f]{64}$")
    raw_id: str = Field(pattern=r"^historical_industry_pilot_raw_[0-9a-f]{64}$")
    status: HistoricalIndustryQualityStatus
    checks: tuple[str, ...] = Field(min_length=1)


class PilotIndustryLineage(BaseModel):
    """Exact source, lifecycle, calendar, and field mappings for one candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lineage_edge_id: str = Field(pattern=r"^lineage_[0-9a-f]{64}$")
    upstream_artifact_ids: tuple[str, ...] = Field(min_length=3)
    calendar_artifact_id: str | None
    transform_version: str
    field_mappings: tuple[str, ...] = Field(min_length=1)


class PilotIndustryPitCandidate(BaseModel):
    """PIT clocks and industry value still outside research authorization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(pattern=r"^historical_industry_pilot_candidate_[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    listing_date: date
    source_kind: str
    taxonomy: str
    industry_code: str = Field(pattern=r"^[A-Z]\d{2}$")
    industry_name: str
    source_available_at: datetime
    eligible_from: datetime
    usable_from: datetime
    unknown_from: date | None
    unknown_until: datetime | None
    quality_status: HistoricalIndustryQualityStatus


class PilotIndustryAdmission(BaseModel):
    """One exactly linked source-only admission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    admission_id: str = Field(pattern=r"^historical_industry_pilot_admission_[0-9a-f]{64}$")
    raw: PilotIndustryRawObservation
    quality: PilotIndustryQualityReport
    lineage: PilotIndustryLineage
    pit_candidate: PilotIndustryPitCandidate
    research_use_authorized: bool

    @model_validator(mode="after")
    def components_match(self) -> Self:
        """Require exact Raw and quality linkage with authorization disabled."""
        if self.quality.raw_id != self.raw.raw_id or self.research_use_authorized:
            message = "pilot admission components differ or research authority was enabled"
            raise ValueError(message)
        return self


class PilotIndustryAdmissionBatch(BaseModel):
    """Content-addressed all-candidate admission coverage report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str = Field(pattern=r"^historical_industry_admission_batch_[0-9a-f]{64}$")
    batch_version: str
    resolution_id: str = Field(pattern=r"^historical_industry_resolution_[0-9a-f]{64}$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    admitted_at: datetime
    admissions: tuple[PilotIndustryAdmission, ...] = Field(min_length=1)
    resolved_count: int = Field(gt=0)
    unknown_interval_count: int = Field(ge=0)
    research_use_authorized: bool
