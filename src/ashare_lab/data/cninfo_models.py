"""Typed CNInfo response boundaries for official listing disclosures."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class CninfoSecurityHit(BaseModel):
    """One security identity returned by CNInfo search."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    code: str = Field(pattern=r"^\d{6}$")
    org_id: str = Field(alias="orgId", min_length=1)
    name: str = Field(alias="zwjc", min_length=1)
    category: str
    delisted: str


class CninfoAnnouncement(BaseModel):
    """One announcement row returned by the official history query."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    announcement_id: str = Field(alias="announcementId", min_length=1)
    title_html: str = Field(alias="announcementTitle", min_length=1)
    announcement_time_ms: int = Field(alias="announcementTime", ge=0)
    adjunct_url: str = Field(alias="adjunctUrl", min_length=1)
    adjunct_size_kb: int = Field(alias="adjunctSize", ge=0)
    adjunct_type: str = Field(alias="adjunctType", min_length=1)
    sec_code: str = Field(alias="secCode", pattern=r"^\d{6}$")
    sec_name: str = Field(alias="secName", min_length=1)
    org_id: str = Field(alias="orgId", min_length=1)


class CninfoAnnouncementResponse(BaseModel):
    """Official announcement query envelope."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    total_announcement: int = Field(alias="totalAnnouncement", ge=0)
    announcements: tuple[CninfoAnnouncement, ...] | None
    has_more: bool = Field(alias="hasMore")


@dataclass(frozen=True, slots=True)
class CninfoSecurityLookup:
    """Exact response bytes and parsed security identities."""

    payload: bytes
    hits: tuple[CninfoSecurityHit, ...]


@dataclass(frozen=True, slots=True)
class CninfoAnnouncementLookup:
    """Exact response bytes for one bounded listing announcement query."""

    payload: bytes


@dataclass(frozen=True, slots=True)
class CninfoPdfDocument:
    """Current official PDF URL and downloaded bytes."""

    url: str
    content: bytes
