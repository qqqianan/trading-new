"""Read-only audit of official CAPCO historical industry archives."""

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Final

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.capco_industry_html import (
    CapcoListEntry,
    parse_capco_archive_list,
    parse_capco_archive_page,
)

CAPCO_ARCHIVE_LIST_URL: Final = "https://www.capco.org.cn/xhgg/hyfl/hyfljg/index.html"
_AUDIT_VERSION: Final = "capco_archive_audit_v1"


class CapcoCoverageStatus(StrEnum):
    """Evidence state for one expected half-year result."""

    FOUND = "FOUND"
    MISSING = "MISSING"


class CapcoArchiveEvidence(BaseModel):
    """Official publication page and code-sorted PDF evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=2000, le=2100)
    half: int = Field(ge=1, le=2)
    title: str = Field(min_length=1)
    page_url: str = Field(min_length=1)
    publication_date: date
    attachment_url: str = Field(min_length=1)
    page_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_bytes: int = Field(gt=0)
    attachment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attachment_bytes: int = Field(gt=0)


class CapcoCoverageCell(BaseModel):
    """One expected half-year and its fail-closed evidence state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=2000, le=2100)
    half: int = Field(ge=1, le=2)
    status: CapcoCoverageStatus
    reason: str
    evidence_attachment_sha256: str | None = None


class CapcoIndustryArchiveAudit(BaseModel):
    """Content-addressed source audit with no research authorization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(pattern=r"^capco_industry_archive_audit_[0-9a-f]{64}$")
    audit_version: str
    source: str
    source_list_url: str
    start_year: int
    end_year: int
    audited_at: datetime
    coverage: tuple[CapcoCoverageCell, ...]
    evidence: tuple[CapcoArchiveEvidence, ...]
    research_use_authorized: bool


def audit_capco_archive(
    client: httpx2.Client,
    *,
    start_year: int,
    end_year: int,
    audited_at: datetime,
) -> CapcoIndustryArchiveAudit:
    """Fetch and hash official half-year pages and code-sorted PDFs."""
    if start_year > end_year:
        msg = "start_year must not be after end_year"
        raise ValueError(msg)
    list_response = client.get(CAPCO_ARCHIVE_LIST_URL)
    list_response.raise_for_status()
    entries = parse_capco_archive_list(list_response.content, CAPCO_ARCHIVE_LIST_URL)
    relevant = tuple(entry for entry in entries if start_year <= entry.year <= end_year)
    evidence, failures = _collect_evidence(client, relevant)
    coverage = _build_coverage(start_year, end_year, evidence, failures, relevant)
    draft = CapcoIndustryArchiveAudit(
        audit_id=f"capco_industry_archive_audit_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        source="China Association for Public Companies",
        source_list_url=CAPCO_ARCHIVE_LIST_URL,
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
        update={"audit_id": f"capco_industry_archive_audit_{hashlib.sha256(payload).hexdigest()}"}
    )


def _collect_evidence(
    client: httpx2.Client,
    entries: tuple[CapcoListEntry, ...],
) -> tuple[tuple[CapcoArchiveEvidence, ...], dict[tuple[int, int], str]]:
    found: list[CapcoArchiveEvidence] = []
    failures: dict[tuple[int, int], str] = {}
    for entry in entries:
        page = client.get(entry.page_url)
        page.raise_for_status()
        metadata = parse_capco_archive_page(page.content, entry.page_url)
        key = (entry.year, entry.half)
        if metadata.publication_date_text is None:
            failures[key] = "content_page_missing_publication_date"
            continue
        if metadata.code_sorted_attachment_url is None:
            failures[key] = "content_page_missing_code_sorted_pdf"
            continue
        attachment = client.get(metadata.code_sorted_attachment_url)
        attachment.raise_for_status()
        if not attachment.content.startswith(b"%PDF"):
            failures[key] = "attachment_is_not_pdf"
            continue
        found.append(
            CapcoArchiveEvidence(
                year=entry.year,
                half=entry.half,
                title=entry.title,
                page_url=entry.page_url,
                publication_date=date.fromisoformat(metadata.publication_date_text),
                attachment_url=metadata.code_sorted_attachment_url,
                page_sha256=hashlib.sha256(page.content).hexdigest(),
                page_bytes=len(page.content),
                attachment_sha256=hashlib.sha256(attachment.content).hexdigest(),
                attachment_bytes=len(attachment.content),
            )
        )
    return tuple(sorted(found, key=lambda item: (item.year, item.half))), failures


def _build_coverage(
    start_year: int,
    end_year: int,
    evidence: tuple[CapcoArchiveEvidence, ...],
    failures: dict[tuple[int, int], str],
    entries: tuple[CapcoListEntry, ...],
) -> tuple[CapcoCoverageCell, ...]:
    evidence_by_key = {(item.year, item.half): item for item in evidence}
    entry_counts: dict[tuple[int, int], int] = {}
    for entry in entries:
        key = (entry.year, entry.half)
        entry_counts[key] = entry_counts.get(key, 0) + 1
    cells: list[CapcoCoverageCell] = []
    for year in range(start_year, end_year + 1):
        for half in range(1, 3):
            key = (year, half)
            item = evidence_by_key.get(key)
            duplicate = entry_counts.get(key, 0) > 1
            status = (
                CapcoCoverageStatus.FOUND
                if item is not None and not duplicate
                else CapcoCoverageStatus.MISSING
            )
            reason = (
                "complete_official_evidence"
                if status is CapcoCoverageStatus.FOUND
                else failures.get(key, "not_in_official_list")
            )
            if duplicate:
                reason = "duplicate_official_list_entries"
            digest = (
                item.attachment_sha256
                if status is CapcoCoverageStatus.FOUND and item is not None
                else None
            )
            cells.append(
                CapcoCoverageCell(
                    year=year,
                    half=half,
                    status=status,
                    reason=reason,
                    evidence_attachment_sha256=digest,
                )
            )
    return tuple(cells)
