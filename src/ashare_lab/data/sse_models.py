"""Typed Shanghai Stock Exchange source boundaries."""

from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SseBulletin(BaseModel):
    """One official company bulletin search result."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    added_at: datetime = Field(alias="ADDDATE")
    security_code: str = Field(alias="SECURITY_CODE", pattern=r"^\d{6}$")
    security_name: str = Field(alias="SECURITY_NAME", min_length=1)
    disclosure_date: date = Field(alias="SSEDATE")
    title: str = Field(alias="TITLE", min_length=1)
    attachment_url: str = Field(alias="URL", min_length=1)


class SseBulletinEnvelope(BaseModel):
    """Official company bulletin response envelope."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    result: tuple[SseBulletin, ...]


@dataclass(frozen=True, slots=True)
class SseBulletinLookup:
    """Exact SSE query bytes and parsed result rows."""

    payload: bytes
    hits: tuple[SseBulletin, ...]


@dataclass(frozen=True, slots=True)
class SsePdfDocument:
    """Final official attachment URL and response bytes."""

    url: str
    content: bytes
