"""Read-only audit of official historical industry classification archives."""

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Final

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.historical_industry_html import (
    ArchiveListEntry,
    parse_archive_list,
    parse_archive_page,
)

CSRC_ARCHIVE_LIST_URL: Final = "https://www.csrc.gov.cn/csrc/c100103/common_list.shtml"
_AUDIT_VERSION: Final = "csrc_archive_audit_v1"


class ArchiveCoverageStatus(StrEnum):
    """Evidence state for one expected calendar quarter."""

    FOUND = "FOUND"
    MISSING = "MISSING"


class ArchiveEvidence(BaseModel):
    """Immutable hashes and publication metadata for one official PDF."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=2000, le=2100)
    quarter: int = Field(ge=1, le=4)
    title: str = Field(min_length=1)
    page_url: str = Field(min_length=1)
    publication_date: date
    attachment_url: str = Field(min_length=1)
    page_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_bytes: int = Field(gt=0)
    attachment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attachment_bytes: int = Field(gt=0)


class ArchiveCoverageCell(BaseModel):
    """One expected quarter and the reason for its evidence state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=2000, le=2100)
    quarter: int = Field(ge=1, le=4)
    status: ArchiveCoverageStatus
    reason: str
    evidence_attachment_sha256: str | None = None


class HistoricalIndustryArchiveAudit(BaseModel):
    """Content-addressed source audit that grants no research-data access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(pattern=r"^industry_archive_audit_[0-9a-f]{64}$")
    audit_version: str
    source: str
    source_list_url: str
    start_year: int
    end_year: int
    audited_at: datetime
    coverage: tuple[ArchiveCoverageCell, ...]
    evidence: tuple[ArchiveEvidence, ...]
    research_use_authorized: bool


def audit_csrc_archive(
    client: httpx2.Client,
    *,
    start_year: int,
    end_year: int,
    audited_at: datetime,
) -> HistoricalIndustryArchiveAudit:
    """Fetch and hash official pages while failing closed on incomplete evidence."""
    if start_year > end_year:
        msg = "start_year must not be after end_year"
        raise ValueError(msg)
    list_response = client.get(CSRC_ARCHIVE_LIST_URL)
    list_response.raise_for_status()
    entries = parse_archive_list(list_response.content, CSRC_ARCHIVE_LIST_URL)
    relevant = tuple(entry for entry in entries if start_year <= entry.year <= end_year)
    evidence, failures = _collect_evidence(client, relevant)
    coverage = _build_coverage(start_year, end_year, evidence, failures, relevant)
    draft = HistoricalIndustryArchiveAudit(
        audit_id=f"industry_archive_audit_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        source="China Securities Regulatory Commission",
        source_list_url=CSRC_ARCHIVE_LIST_URL,
        start_year=start_year,
        end_year=end_year,
        audited_at=audited_at,
        coverage=coverage,
        evidence=evidence,
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"audit_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return draft.model_copy(
        update={"audit_id": f"industry_archive_audit_{hashlib.sha256(payload).hexdigest()}"}
    )


def _collect_evidence(
    client: httpx2.Client,
    entries: tuple[ArchiveListEntry, ...],
) -> tuple[tuple[ArchiveEvidence, ...], dict[tuple[int, int], str]]:
    found: list[ArchiveEvidence] = []
    failures: dict[tuple[int, int], str] = {}
    for entry in entries:
        page = client.get(entry.page_url)
        page.raise_for_status()
        metadata = parse_archive_page(page.content, entry.page_url)
        key = (entry.year, entry.quarter)
        if metadata.publication_date_text is None:
            failures[key] = "content_page_missing_publication_date"
            continue
        if metadata.attachment_url is None:
            failures[key] = "content_page_missing_pdf"
            continue
        attachment = client.get(metadata.attachment_url)
        attachment.raise_for_status()
        if not attachment.content.startswith(b"%PDF"):
            failures[key] = "attachment_is_not_pdf"
            continue
        found.append(
            ArchiveEvidence(
                year=entry.year,
                quarter=entry.quarter,
                title=metadata.title or entry.title,
                page_url=entry.page_url,
                publication_date=date.fromisoformat(metadata.publication_date_text),
                attachment_url=metadata.attachment_url,
                page_sha256=hashlib.sha256(page.content).hexdigest(),
                page_bytes=len(page.content),
                attachment_sha256=hashlib.sha256(attachment.content).hexdigest(),
                attachment_bytes=len(attachment.content),
            )
        )
    return tuple(sorted(found, key=lambda item: (item.year, item.quarter))), failures


def _build_coverage(
    start_year: int,
    end_year: int,
    evidence: tuple[ArchiveEvidence, ...],
    failures: dict[tuple[int, int], str],
    entries: tuple[ArchiveListEntry, ...],
) -> tuple[ArchiveCoverageCell, ...]:
    evidence_by_key = {(item.year, item.quarter): item for item in evidence}
    entry_counts: dict[tuple[int, int], int] = {}
    for entry in entries:
        key = (entry.year, entry.quarter)
        entry_counts[key] = entry_counts.get(key, 0) + 1
    cells: list[ArchiveCoverageCell] = []
    for year in range(start_year, end_year + 1):
        for quarter in range(1, 5):
            key = (year, quarter)
            item = evidence_by_key.get(key)
            duplicate = entry_counts.get(key, 0) > 1
            status = (
                ArchiveCoverageStatus.FOUND
                if item is not None and not duplicate
                else ArchiveCoverageStatus.MISSING
            )
            reason = (
                "complete_official_evidence"
                if status is ArchiveCoverageStatus.FOUND
                else failures.get(key, "not_in_official_list")
            )
            if duplicate:
                reason = "duplicate_official_list_entries"
            cells.append(
                ArchiveCoverageCell(
                    year=year,
                    quarter=quarter,
                    status=status,
                    reason=reason,
                    evidence_attachment_sha256=item.attachment_sha256
                    if status is ArchiveCoverageStatus.FOUND and item is not None
                    else None,
                )
            )
    return tuple(cells)
