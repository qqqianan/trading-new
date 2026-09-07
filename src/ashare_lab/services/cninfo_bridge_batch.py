"""Content-addressed batch evidence for the fixed CNInfo bridge pilot."""

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
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection

_BATCH_VERSION: Final = "cninfo_bridge_batch_audit_v1"


class CategoryCount(BaseModel):
    """Stable count for one batch outcome category."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    count: int = Field(gt=0)


class CninfoBridgeBatchAudit(BaseModel):
    """Source-only batch report that retains every preselected failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str = Field(pattern=r"^cninfo_bridge_batch_audit_[0-9a-f]{64}$")
    batch_version: str
    audited_at: datetime
    selection: StratifiedCandidateSelection
    audits: tuple[CninfoIndustryBridgeAudit, ...]
    found_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    timestamp_precision_counts: tuple[CategoryCount, ...]
    taxonomy_counts: tuple[CategoryCount, ...]
    failure_counts: tuple[CategoryCount, ...]
    research_use_authorized: bool


class CninfoBridgeBatchError(Exception):
    """Individual audit evidence does not match the preregistered selection."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one exact candidate-linkage failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the batch boundary and stable failure detail."""
        return f"cninfo_bridge_batch: {self.detail}"


def build_cninfo_bridge_batch(
    selection: StratifiedCandidateSelection,
    audits: tuple[CninfoIndustryBridgeAudit, ...],
    *,
    audited_at: datetime,
) -> CninfoBridgeBatchAudit:
    """Bind individual audits to exact selected keys without replacement."""
    expected = tuple((item.symbol, item.listing_date) for item in selection.selected)
    observed = tuple((audit.candidate.symbol, audit.candidate.listing_date) for audit in audits)
    if observed != expected:
        detail = "individual audit keys differ from ordered selection"
        raise CninfoBridgeBatchError(detail)
    if any(audit.research_use_authorized for audit in audits):
        detail = "individual source audit attempted to authorize research use"
        raise CninfoBridgeBatchError(detail)
    found = tuple(audit for audit in audits if audit.status is BridgeStatus.FOUND)
    missing = tuple(audit for audit in audits if audit.status is BridgeStatus.MISSING)
    precision = Counter(
        audit.evidence.timestamp_precision.value for audit in found if audit.evidence is not None
    )
    taxonomy = Counter(audit.evidence.taxonomy for audit in found if audit.evidence is not None)
    failures = Counter(
        audit.failure_reason for audit in missing if audit.failure_reason is not None
    )
    draft = CninfoBridgeBatchAudit(
        batch_id=f"cninfo_bridge_batch_audit_{'0' * 64}",
        batch_version=_BATCH_VERSION,
        audited_at=audited_at,
        selection=selection,
        audits=audits,
        found_count=len(found),
        missing_count=len(missing),
        timestamp_precision_counts=_category_counts(precision),
        taxonomy_counts=_category_counts(taxonomy),
        failure_counts=_category_counts(failures),
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"batch_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"batch_id": f"cninfo_bridge_batch_audit_{digest}"})


def _category_counts(counts: Counter[str]) -> tuple[CategoryCount, ...]:
    return tuple(
        CategoryCount(category=category, count=count) for category, count in sorted(counts.items())
    )
