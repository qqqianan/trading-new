"""Frozen unified observations from official historical-industry sources."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HistoricalIndustrySourceKind(StrEnum):
    """Closed official source branches retained in pilot attribution."""

    CNINFO_LISTING = "CNINFO_LISTING"
    CNINFO_PROSPECTUS = "CNINFO_PROSPECTUS"
    SSE_PROSPECTUS = "SSE_PROSPECTUS"
    CAPCO_MEMBERSHIP = "CAPCO_MEMBERSHIP"


class HistoricalIndustrySourceError(Exception):
    """A source audit cannot become one exact unified observation."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one stable source-adapter failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the unified source boundary and concrete reason."""
        return f"historical_industry_source: {self.detail}"


class HistoricalIndustrySourceObservation(BaseModel):
    """One exact official classification before calendar availability projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(pattern=r"^historical_industry_source_[0-9a-f]{64}$")
    source_kind: HistoricalIndustrySourceKind
    source_audit_id: str = Field(min_length=1)
    parent_audit_ids: tuple[str, ...]
    audited_at: datetime
    symbol: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    listing_date: date
    provider_published_at: datetime
    provider_publication_date: date
    timestamp_precision: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page_number: int | None = Field(default=None, gt=0)
    security_name: str | None
    taxonomy: str
    industry_code: str = Field(pattern=r"^[A-Z]\d{2}$")
    industry_name: str
    unknown_from: date | None
    research_use_authorized: bool
