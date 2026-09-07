"""Content-addressed trade-calendar evidence for date-only source availability."""

import hashlib
import json
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field


class HistoricalIndustryCalendarError(Exception):
    """Canonical calendar rows cannot prove the first later session open."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one stable calendar-evidence failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the calendar boundary and concrete reason."""
        return f"historical_industry_calendar: {self.detail}"


class HistoricalIndustryCalendarRow(BaseModel):
    """Exact accepted canonical row and its Raw identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cal_date: str = Field(pattern=r"^\d{8}$")
    exchange: str = Field(pattern=r"^SSE$")
    is_open: int = Field(ge=0, le=1)
    quality_status: str
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    source_snapshot_id: str = Field(pattern=r"^snap_[0-9a-f]{64}$")
    source_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def date(self) -> date:
        """Parse the provider calendar date after boundary validation."""
        return date.fromisoformat(f"{self.cal_date[:4]}-{self.cal_date[4:6]}-{self.cal_date[6:]}")


class HistoricalIndustryCalendarEvidence(BaseModel):
    """Minimal continuous calendar interval proving one next-open date."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    calendar_artifact_id: str = Field(pattern=r"^historical_industry_calendar_[0-9a-f]{64}$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]{64}$")
    start_date: date
    end_date: date
    next_open_date: date
    rows_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: tuple[HistoricalIndustryCalendarRow, ...] = Field(min_length=2)
    quality_status: str = Field(pattern=r"^QUALIFIED_FOR_AVAILABILITY_PROJECTION$")


def build_historical_industry_calendar(
    rows: tuple[HistoricalIndustryCalendarRow, ...],
    *,
    publication_date: date,
) -> HistoricalIndustryCalendarEvidence:
    """Freeze every accepted natural day through the first later SSE open."""
    if not rows:
        detail = "canonical trade calendar is empty"
        raise HistoricalIndustryCalendarError(detail)
    by_date: dict[str, HistoricalIndustryCalendarRow] = {}
    for row in rows:
        previous = by_date.get(row.cal_date)
        if previous is not None and previous != row:
            detail = "canonical trade calendar contains a conflicting duplicate natural key"
            raise HistoricalIndustryCalendarError(detail)
        by_date[row.cal_date] = row
    ordered = tuple(sorted(by_date.values(), key=lambda row: row.cal_date))
    schema_ids = {row.schema_manifest_id for row in ordered}
    valid = (
        len(schema_ids) == 1
        and all(row.exchange == "SSE" for row in ordered)
        and all(row.quality_status == "ACCEPTED" for row in ordered)
    )
    if not valid:
        detail = "calendar rows cross exchange, schema, or quality boundaries"
        raise HistoricalIndustryCalendarError(detail)
    future_open = tuple(row for row in ordered if row.date > publication_date and row.is_open == 1)
    if not future_open:
        detail = "calendar has no later accepted open session"
        raise HistoricalIndustryCalendarError(detail)
    next_open = future_open[0].date
    bounded = tuple(row for row in ordered if publication_date <= row.date <= next_open)
    expected = tuple(
        publication_date + timedelta(days=offset)
        for offset in range((next_open - publication_date).days + 1)
    )
    if tuple(row.date for row in bounded) != expected:
        detail = "calendar rows are not continuous through the next open"
        raise HistoricalIndustryCalendarError(detail)
    row_payload = tuple(row.model_dump(mode="json") for row in bounded)
    serialized = json.dumps(row_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    rows_sha256 = hashlib.sha256(serialized.encode()).hexdigest()
    schema_manifest_id = bounded[0].schema_manifest_id
    identity = f"{schema_manifest_id}|{publication_date.isoformat()}|{rows_sha256}"
    return HistoricalIndustryCalendarEvidence(
        calendar_artifact_id=(
            f"historical_industry_calendar_{hashlib.sha256(identity.encode()).hexdigest()}"
        ),
        schema_manifest_id=schema_manifest_id,
        start_date=publication_date,
        end_date=next_open,
        next_open_date=next_open,
        rows_sha256=rows_sha256,
        rows=bounded,
        quality_status="QUALIFIED_FOR_AVAILABILITY_PROJECTION",
    )
