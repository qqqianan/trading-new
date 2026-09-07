"""Frozen source-only admission contracts for official historical industries."""

from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HistoricalIndustryQualityStatus(StrEnum):
    """Closed quality result before research-data authorization exists."""

    QUALIFIED_SOURCE_ONLY = "QUALIFIED_SOURCE_ONLY"


class HistoricalIndustryAdmissionError(Exception):
    """Source, schema, quality, or calendar evidence cannot support admission."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one stable fail-closed admission reason."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the historical-industry boundary and reason."""
        return f"historical_industry_admission: {self.detail}"


class HistoricalIndustryRawObservation(BaseModel):
    """Immutable source observation derived from one exact source audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_id: str = Field(pattern=r"^historical_industry_raw_[0-9a-f]{64}$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    parent_source_audit_id: str = Field(pattern=r"^capco_membership_audit_[0-9a-f]{64}$")
    parent_archive_audit_id: str = Field(pattern=r"^capco_industry_archive_audit_[0-9a-f]{64}$")
    parent_conflict_audit_id: str = Field(pattern=r"^cninfo_industry_bridge_audit_[0-9a-f]{64}$")
    observed_at: datetime
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page_number: int = Field(gt=0)
    symbol: str = Field(pattern=r"^\d{6}\.SH$")
    security_name: str = Field(min_length=1)
    taxonomy: str = Field(pattern=r"^CAPCO_\d{4}$")
    industry_code: str = Field(pattern=r"^[A-Z]\d{2}$")
    industry_name: str = Field(min_length=1)
    unknown_from: date
    provider_publication_date: date


class HistoricalIndustryQualityReport(BaseModel):
    """Fail-closed checks over one exact historical-industry Raw observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quality_report_id: str = Field(pattern=r"^historical_industry_quality_[0-9a-f]{64}$")
    raw_id: str = Field(pattern=r"^historical_industry_raw_[0-9a-f]{64}$")
    status: HistoricalIndustryQualityStatus
    checks: tuple[str, ...] = Field(min_length=1)


class HistoricalIndustryLineage(BaseModel):
    """Field-level source and calendar lineage for one PIT candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lineage_edge_id: str = Field(pattern=r"^lineage_[0-9a-f]{64}$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    upstream_artifact_ids: tuple[str, ...] = Field(min_length=2)
    calendar_artifact_id: str = Field(min_length=1)
    calendar_dates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform_name: str
    transform_version: str
    field_mappings: tuple[str, ...] = Field(min_length=1)


class HistoricalIndustryPitCandidate(BaseModel):
    """Unavailable-before projection that remains outside the research data plane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(pattern=r"^historical_industry_pit_candidate_[0-9a-f]{64}$")
    source_raw_id: str = Field(pattern=r"^historical_industry_raw_[0-9a-f]{64}$")
    quality_report_id: str = Field(pattern=r"^historical_industry_quality_[0-9a-f]{64}$")
    lineage_edge_id: str = Field(pattern=r"^lineage_[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^\d{6}\.SH$")
    security_name: str
    taxonomy: str
    industry_code: str = Field(pattern=r"^[A-Z]\d{2}$")
    industry_name: str
    unknown_from: date
    provider_publication_date: date
    available_at: datetime
    quality_status: HistoricalIndustryQualityStatus


class HistoricalIndustryAdmission(BaseModel):
    """Content-addressed admission evidence with research authority disabled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    admission_id: str = Field(pattern=r"^historical_industry_admission_[0-9a-f]{64}$")
    admission_version: str
    admitted_at: datetime
    raw: HistoricalIndustryRawObservation
    quality: HistoricalIndustryQualityReport
    lineage: HistoricalIndustryLineage
    pit_candidate: HistoricalIndustryPitCandidate
    research_use_authorized: bool

    @model_validator(mode="after")
    def linked_components_match(self) -> Self:
        """Require exact Raw, quality, lineage, and PIT component linkage."""
        linked = (
            self.quality.raw_id == self.raw.raw_id
            and self.pit_candidate.source_raw_id == self.raw.raw_id
            and self.pit_candidate.quality_report_id == self.quality.quality_report_id
            and self.pit_candidate.lineage_edge_id == self.lineage.lineage_edge_id
            and self.lineage.schema_manifest_id == self.raw.schema_manifest_id
            and not self.research_use_authorized
        )
        if not linked:
            message = "historical industry admission components are not exactly linked"
            raise ValueError(message)
        return self
