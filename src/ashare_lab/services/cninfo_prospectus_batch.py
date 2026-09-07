"""Supplemental batch governance for fixed CNInfo prospectus candidates."""

import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.cninfo_industry_bridge import (
    BridgeStatus,
    CninfoIndustryBridgeAudit,
)
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    ProspectusBridgeCandidate,
)
from ashare_lab.services.cninfo_bridge_batch import CategoryCount

_BATCH_VERSION: Final = "cninfo_prospectus_bridge_batch_v3"
_ELIGIBLE_REASON: Final = "explicit_industry_disclosure_missing"


class CninfoProspectusBatchAudit(BaseModel):
    """Content-addressed supplement bound to one immutable base batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str = Field(pattern=r"^cninfo_prospectus_bridge_batch_[0-9a-f]{64}$")
    batch_version: str
    parent_batch_id: str = Field(pattern=r"^cninfo_bridge_batch_audit_[0-9a-f]{64}$")
    audited_at: datetime
    candidates: tuple[ProspectusBridgeCandidate, ...]
    audits: tuple[CninfoProspectusBridgeAudit, ...]
    found_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    taxonomy_counts: tuple[CategoryCount, ...]
    failure_counts: tuple[CategoryCount, ...]
    research_use_authorized: bool


class CninfoProspectusBatchError(Exception):
    """Supplemental audits do not match their exact eligible parent set."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one fail-closed linkage error."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the supplemental batch boundary and detail."""
        return f"cninfo_prospectus_batch: {self.detail}"


def eligible_prospectus_candidates(
    base_audits: tuple[CninfoIndustryBridgeAudit, ...],
) -> tuple[ProspectusBridgeCandidate, ...]:
    """Derive exact parent-linked candidates without admitting conflicts."""
    return tuple(
        ProspectusBridgeCandidate(
            parent_audit_id=audit.audit_id,
            symbol=audit.candidate.symbol,
            listing_date=audit.candidate.listing_date,
        )
        for audit in base_audits
        if audit.status is BridgeStatus.MISSING and audit.failure_reason == _ELIGIBLE_REASON
    )


def build_cninfo_prospectus_batch(
    parent_batch_id: str,
    candidates: tuple[ProspectusBridgeCandidate, ...],
    audits: tuple[CninfoProspectusBridgeAudit, ...],
    *,
    audited_at: datetime,
) -> CninfoProspectusBatchAudit:
    """Bind every supplemental outcome to the ordered eligible parent audits."""
    if tuple(audit.candidate for audit in audits) != candidates:
        detail = "supplemental audit candidates differ from ordered parent set"
        raise CninfoProspectusBatchError(detail)
    if any(audit.research_use_authorized for audit in audits):
        detail = "supplemental source audit attempted to authorize research use"
        raise CninfoProspectusBatchError(detail)
    found = tuple(audit for audit in audits if audit.status is BridgeStatus.FOUND)
    missing = tuple(audit for audit in audits if audit.status is BridgeStatus.MISSING)
    taxonomy = Counter(audit.evidence.taxonomy for audit in found if audit.evidence is not None)
    failures = Counter(
        audit.failure_reason for audit in missing if audit.failure_reason is not None
    )
    draft = CninfoProspectusBatchAudit(
        batch_id=f"cninfo_prospectus_bridge_batch_{'0' * 64}",
        batch_version=_BATCH_VERSION,
        parent_batch_id=parent_batch_id,
        audited_at=audited_at,
        candidates=candidates,
        audits=audits,
        found_count=len(found),
        missing_count=len(missing),
        taxonomy_counts=_counts(taxonomy),
        failure_counts=_counts(failures),
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"batch_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"batch_id": f"cninfo_prospectus_bridge_batch_{digest}"})


def _counts(counts: Counter[str]) -> tuple[CategoryCount, ...]:
    return tuple(
        CategoryCount(category=category, count=count) for category, count in sorted(counts.items())
    )
