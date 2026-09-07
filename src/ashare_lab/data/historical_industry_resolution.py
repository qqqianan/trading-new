"""Deterministic source selection for the fixed historical-industry pilot."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.cninfo_industry_bridge import BridgeStatus, CninfoIndustryBridgeAudit
from ashare_lab.data.cninfo_observation_models import (
    CninfoProspectusConsistencyAudit,
    ConsistencyStatus,
)
from ashare_lab.data.cninfo_prospectus_bridge import CninfoProspectusBridgeAudit
from ashare_lab.data.historical_industry_resolution_lookup import (
    ResolutionLookup,
    build_resolution_lookup,
    required,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionCount,
    HistoricalIndustryResolutionError,
    HistoricalIndustryResolutionReport,
    HistoricalIndustryResolutionRow,
)
from ashare_lab.data.historical_industry_source_models import (
    HistoricalIndustrySourceKind,
    HistoricalIndustrySourceObservation,
)
from ashare_lab.data.historical_industry_sources import (
    source_from_capco,
    source_from_cninfo,
    source_from_cninfo_prospectus,
    source_from_sse,
)
from ashare_lab.data.official_bridge_candidates import OfficialBridgeCandidate
from ashare_lab.data.sse_industry_models import SseProspectusIndustryAudit
from ashare_lab.services.cninfo_bridge_batch import CninfoBridgeBatchAudit
from ashare_lab.services.cninfo_prospectus_batch import CninfoProspectusBatchAudit

_RESOLUTION_VERSION: Final = "historical_industry_resolution_v1"
_MISSING: Final = "explicit_industry_disclosure_missing"
_CONFLICTING: Final = "explicit_industry_disclosure_conflicting"


@dataclass(frozen=True, slots=True)
class HistoricalIndustryResolutionInputs:
    """Exact parent batches and independent source-only resolution evidence."""

    base: CninfoBridgeBatchAudit
    supplemental: CninfoProspectusBatchAudit
    consistencies: tuple[CninfoProspectusConsistencyAudit, ...]
    sse_audits: tuple[SseProspectusIndustryAudit, ...]
    capco_audits: tuple[CapcoMembershipAudit, ...]


def resolve_historical_industry_pilot(
    inputs: HistoricalIndustryResolutionInputs,
    *,
    resolved_at: datetime,
) -> HistoricalIndustryResolutionReport:
    """Resolve every fixed candidate once without outcome-dependent replacement."""
    base = inputs.base
    supplemental = inputs.supplemental
    _validate_parent_batches(base, supplemental)
    lookup = build_resolution_lookup(
        supplemental.audits,
        inputs.consistencies,
        inputs.sse_audits,
        inputs.capco_audits,
    )
    rows = tuple(
        _resolve_row(
            candidate,
            base_audit,
            lookup,
        )
        for candidate, base_audit in zip(base.selection.selected, base.audits, strict=True)
    )
    counts = Counter(row.source.source_kind for row in rows)
    draft = HistoricalIndustryResolutionReport(
        resolution_id=f"historical_industry_resolution_{'0' * 64}",
        resolution_version=_RESOLUTION_VERSION,
        resolved_at=resolved_at,
        selection_id=base.selection.selection_id,
        parent_base_batch_id=base.batch_id,
        parent_supplemental_batch_id=supplemental.batch_id,
        rows=rows,
        resolved_count=len(rows),
        source_counts=tuple(
            HistoricalIndustryResolutionCount(source_kind=kind, count=counts[kind])
            for kind in HistoricalIndustrySourceKind
            if counts[kind] > 0
        ),
        research_use_authorized=False,
    )
    payload = json.dumps(
        draft.model_dump(mode="json", exclude={"resolution_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return draft.model_copy(update={"resolution_id": f"historical_industry_resolution_{digest}"})


def _validate_parent_batches(
    base: CninfoBridgeBatchAudit,
    supplemental: CninfoProspectusBatchAudit,
) -> None:
    expected = tuple((item.symbol, item.listing_date) for item in base.selection.selected)
    observed = tuple((item.candidate.symbol, item.candidate.listing_date) for item in base.audits)
    valid = (
        supplemental.parent_batch_id == base.batch_id
        and expected == observed
        and not base.research_use_authorized
        and not supplemental.research_use_authorized
    )
    if not valid:
        detail = "base, selection, or supplemental batch linkage differs"
        raise HistoricalIndustryResolutionError(detail)


def _resolve_row(
    candidate: OfficialBridgeCandidate,
    base_audit: CninfoIndustryBridgeAudit,
    lookup: ResolutionLookup,
) -> HistoricalIndustryResolutionRow:
    evaluated = [base_audit.audit_id]
    if base_audit.status is BridgeStatus.FOUND:
        source = source_from_cninfo(base_audit)
        reason = "BASE_LISTING_DISCLOSURE_FOUND"
    elif base_audit.failure_reason == _MISSING:
        supplement = required(lookup.supplements, base_audit.audit_id, "supplemental audit")
        evaluated.append(supplement.audit_id)
        consistency = lookup.consistencies.get(base_audit.audit_id)
        if consistency is None:
            source = source_from_cninfo_prospectus(supplement)
            reason = "STABLE_SUPPLEMENTAL_PROSPECTUS_FOUND"
        else:
            source, reason = _resolve_unstable(
                supplement,
                consistency,
                lookup.sse_audits,
                evaluated,
            )
    elif base_audit.failure_reason == _CONFLICTING:
        capco = required(
            lookup.capco_audits,
            base_audit.audit_id,
            "CAPCO conflict resolution",
        )
        evaluated.append(capco.audit_id)
        source = source_from_capco(capco)
        reason = "CONFLICTING_IPO_DISCLOSURE_RESOLVED_BY_LATER_CAPCO"
    else:
        detail = f"unsupported base outcome for {candidate.symbol}"
        raise HistoricalIndustryResolutionError(detail)
    if source.symbol != candidate.symbol or source.listing_date != candidate.listing_date:
        detail = f"selected source key differs for {candidate.symbol}"
        raise HistoricalIndustryResolutionError(detail)
    return HistoricalIndustryResolutionRow(
        symbol=candidate.symbol,
        listing_date=candidate.listing_date,
        universe_event_ids=candidate.source_event_ids,
        universe_schema_manifest_id=candidate.universe_schema_manifest_id,
        base_audit_id=base_audit.audit_id,
        evaluated_audit_ids=tuple(evaluated),
        selection_reason=reason,
        source=source,
    )


def _resolve_unstable(
    supplement: CninfoProspectusBridgeAudit,
    consistency: CninfoProspectusConsistencyAudit,
    sse_audits: dict[str, SseProspectusIndustryAudit],
    evaluated: list[str],
) -> tuple[HistoricalIndustrySourceObservation, str]:
    valid = (
        consistency.status is ConsistencyStatus.UNSTABLE
        and consistency.reason == "query_outcome_changed"
        and not consistency.research_use_authorized
    )
    if not valid:
        detail = "CNInfo consistency is not the registered unstable contradiction"
        raise HistoricalIndustryResolutionError(detail)
    evaluated.append(consistency.consistency_id)
    sse = required(sse_audits, consistency.consistency_id, "SSE confirmation")
    evaluated.append(sse.audit_id)
    source = source_from_sse(sse)
    supplement_source = source_from_cninfo_prospectus(supplement)
    if source.document_sha256 != supplement_source.document_sha256:
        detail = "SSE and CNInfo successful document hashes differ"
        raise HistoricalIndustryResolutionError(detail)
    return source, "UNSTABLE_CNINFO_REQUIRES_SSE_CONFIRMATION"
