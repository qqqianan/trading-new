"""Parent-linked source audit for one CAPCO historical membership row."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from ashare_lab.data.capco_industry_archives import CapcoIndustryArchiveAudit
from ashare_lab.data.capco_membership_models import (
    CapcoMembershipAudit,
    CapcoMembershipCandidate,
    CapcoMembershipEvidence,
    CapcoMembershipStatus,
    CapcoPdfDocument,
    CapcoTemporalResolution,
)
from ashare_lab.data.capco_pdf import CapcoPdfExtractionError, extract_capco_layout_pages
from ashare_lab.data.cninfo_industry_bridge import BridgeStatus, CninfoIndustryBridgeAudit

_AUDIT_VERSION: Final = "capco_membership_audit_v2"
_PENDING_AVAILABILITY: Final = "PENDING_NEXT_TRADING_SESSION_OPEN"
LayoutPageExtractor = Callable[[bytes], tuple[str, ...]]


class CapcoMembershipProvider(Protocol):
    """Minimal rate-limited attachment capability required by the audit."""

    def fetch_pdf(self, url: str) -> CapcoPdfDocument:
        """Return the exact official attachment bytes."""
        ...


class CapcoMembershipError(Exception):
    """Parent evidence or membership rows are ambiguous."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one fail-closed parent or row ambiguity."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the CAPCO boundary and failure detail."""
        return f"capco_membership: {self.detail}"


@dataclass(frozen=True, slots=True)
class ParsedCapcoMembership:
    """Unambiguous company classification recovered from layout text."""

    security_code: str
    security_name: str
    industry_code: str
    industry_name: str
    page_number: int


def parse_capco_membership(pages: tuple[str, ...], security_code: str) -> ParsedCapcoMembership:
    """Recover exactly one code-sorted CAPCO row and its wrapped industry name."""
    row_pattern = re.compile(
        rf"^\s*{re.escape(security_code)}\s+(\S+)\s+([A-Z])\s+.+?\s+"
        rf"(\d{{2}})(?:\s{{2,}}(\S.*))?\s*$"
    )
    matches: list[ParsedCapcoMembership] = []
    for page_number, page in enumerate(pages, start=1):
        lines = page.splitlines()
        for row_index, line in enumerate(lines):
            match = row_pattern.match(line)
            if match is None:
                continue
            previous = lines[row_index - 1] if row_index > 0 else ""
            following = lines[row_index + 1] if row_index + 1 < len(lines) else ""
            same_row_prefix = match.group(4)
            if same_row_prefix is None and re.match(r"^\s*\d{6}\s+", previous):
                detail = "wrapped industry prefix is not distinguishable from prior row"
                raise CapcoMembershipError(detail)
            prefix = previous if same_row_prefix is None else same_row_prefix
            industry_name = _compact(prefix) + _compact(following)
            matches.append(
                ParsedCapcoMembership(
                    security_code=security_code,
                    security_name=match.group(1),
                    industry_code=f"{match.group(2)}{match.group(3)}",
                    industry_name=industry_name,
                    page_number=page_number,
                )
            )
    if len(matches) != 1:
        detail = "expected exactly one security row"
        raise CapcoMembershipError(detail)
    parsed = matches[0]
    if not parsed.industry_name:
        detail = "company industry name is missing"
        raise CapcoMembershipError(detail)
    return parsed


def build_capco_membership_candidate(
    archive: CapcoIndustryArchiveAudit,
    conflict: CninfoIndustryBridgeAudit,
    *,
    year: int,
    half: int,
) -> CapcoMembershipCandidate:
    """Bind one exact archive attachment to one exact unresolved IPO conflict."""
    valid_conflict = (
        conflict.status is BridgeStatus.MISSING
        and conflict.failure_reason == "explicit_industry_disclosure_conflicting"
        and conflict.evidence is None
        and not conflict.research_use_authorized
    )
    if not valid_conflict:
        detail = "parent CNInfo audit is not an unresolved disclosure conflict"
        raise CapcoMembershipError(detail)
    evidence = tuple(item for item in archive.evidence if item.year == year and item.half == half)
    if len(evidence) != 1 or archive.research_use_authorized:
        detail = "expected exactly one non-authorized CAPCO archive evidence row"
        raise CapcoMembershipError(detail)
    selected = evidence[0]
    return CapcoMembershipCandidate(
        parent_archive_audit_id=archive.audit_id,
        parent_conflict_audit_id=conflict.audit_id,
        symbol=conflict.candidate.symbol,
        listing_date=conflict.candidate.listing_date,
        year=year,
        half=half,
        publication_date=selected.publication_date,
        attachment_url=selected.attachment_url,
        expected_attachment_sha256=selected.attachment_sha256,
    )


def audit_capco_membership(
    provider: CapcoMembershipProvider,
    candidate: CapcoMembershipCandidate,
    *,
    audited_at: datetime,
    page_extractor: LayoutPageExtractor = extract_capco_layout_pages,
) -> CapcoMembershipAudit:
    """Audit a later official classification without backdating its availability."""
    document = provider.fetch_pdf(candidate.attachment_url)
    digest = hashlib.sha256(document.content).hexdigest()
    if digest != candidate.expected_attachment_sha256:
        return _report(candidate, audited_at, "attachment_hash_mismatch", None)
    if not document.content.startswith(b"%PDF"):
        return _report(candidate, audited_at, "attachment_is_not_pdf", None)
    try:
        pages = page_extractor(document.content)
        parsed = parse_capco_membership(pages, candidate.symbol.split(".", maxsplit=1)[0])
    except CapcoPdfExtractionError:
        return _report(candidate, audited_at, "pdf_layout_extraction_failed", None)
    except CapcoMembershipError:
        return _report(candidate, audited_at, "membership_row_not_unique", None)
    evidence = CapcoMembershipEvidence(
        attachment_url=document.url,
        attachment_sha256=digest,
        attachment_bytes=len(document.content),
        security_code=parsed.security_code,
        security_name=parsed.security_name,
        industry_code=parsed.industry_code,
        industry_name=parsed.industry_name,
        page_number=parsed.page_number,
    )
    return _report(candidate, audited_at, None, evidence)


def _compact(value: str) -> str:
    return "".join(value.split())


def _report(
    candidate: CapcoMembershipCandidate,
    audited_at: datetime,
    failure_reason: str | None,
    evidence: CapcoMembershipEvidence | None,
) -> CapcoMembershipAudit:
    status = CapcoMembershipStatus.FOUND if evidence is not None else CapcoMembershipStatus.MISSING
    draft = CapcoMembershipAudit(
        audit_id=f"capco_membership_audit_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        audited_at=audited_at,
        candidate=candidate,
        status=status,
        failure_reason=failure_reason,
        evidence=evidence,
        temporal_resolution=CapcoTemporalResolution(
            unknown_from=candidate.listing_date,
            provider_publication_date=candidate.publication_date,
            availability_status=_PENDING_AVAILABILITY,
        ),
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"audit_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"audit_id": f"capco_membership_audit_{digest}"})
