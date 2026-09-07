"""Fail-closed consistency evidence for repeated CNInfo prospectus queries."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Final

from pydantic import BaseModel

from ashare_lab.data.cninfo_industry_bridge import BridgeStatus
from ashare_lab.data.cninfo_observation_models import (
    CninfoProspectusConsistencyAudit,
    ConsistencyStatus,
    ProspectusConsistencyError,
    ProspectusQueryObservation,
    ProspectusQuerySpec,
    QueryOutcome,
)
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    ProspectusBridgeCandidate,
)

_AUDIT_VERSION: Final = "cninfo_prospectus_consistency_audit_v1"
_QUERY_VERSION: Final = "cninfo_prospectus_query_v1"
_MINIMUM_OBSERVATIONS: Final = 3
_COMPATIBLE_SOURCE_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "cninfo_prospectus_bridge_audit_v1",
        "cninfo_prospectus_bridge_audit_v2",
        "cninfo_prospectus_bridge_audit_v3",
        "cninfo_prospectus_bridge_audit_v4",
        "cninfo_prospectus_bridge_audit_v5",
        "cninfo_prospectus_bridge_audit_v6",
    }
)


def build_prospectus_consistency_audit(
    candidate: ProspectusBridgeCandidate,
    audits: tuple[CninfoProspectusBridgeAudit, ...],
    *,
    assessed_at: datetime,
) -> CninfoProspectusConsistencyAudit:
    """Assess every retained comparable observation without selecting a winner."""
    if not audits:
        detail = "at least one source audit is required"
        raise ProspectusConsistencyError(detail)
    if any(audit.candidate != candidate for audit in audits):
        detail = "source audit candidate differs"
        raise ProspectusConsistencyError(detail)
    if any(audit.audit_version not in _COMPATIBLE_SOURCE_VERSIONS for audit in audits):
        detail = "source audit version has unregistered query semantics"
        raise ProspectusConsistencyError(detail)
    observations = tuple(sorted((_observation(audit) for audit in audits), key=_sort_key))
    audit_ids = tuple(observation.source_audit_id for observation in observations)
    if len(set(audit_ids)) != len(audit_ids):
        detail = "duplicate source audit identity"
        raise ProspectusConsistencyError(detail)
    org_ids = {_org_id(audit) for audit in audits}
    if len(org_ids) != 1:
        detail = "provider organization identity changed"
        raise ProspectusConsistencyError(detail)
    query = _query_spec(candidate, org_ids.pop())
    status, reason = _classify(observations)
    stable_id = (
        observations[0].announcement_id if status is ConsistencyStatus.STABLE_FOUND else None
    )
    stable_pdf = observations[0].pdf_sha256 if status is ConsistencyStatus.STABLE_FOUND else None
    draft = CninfoProspectusConsistencyAudit(
        consistency_id=f"cninfo_prospectus_consistency_audit_{'0' * 64}",
        audit_version=_AUDIT_VERSION,
        assessed_at=assessed_at,
        candidate=candidate,
        query=query,
        observations=observations,
        minimum_observations=_MINIMUM_OBSERVATIONS,
        status=status,
        reason=reason,
        stable_announcement_id=stable_id,
        stable_pdf_sha256=stable_pdf,
        research_use_authorized=False,
    )
    digest = _model_digest(draft, "consistency_id")
    return draft.model_copy(
        update={"consistency_id": f"cninfo_prospectus_consistency_audit_{digest}"}
    )


def _observation(audit: CninfoProspectusBridgeAudit) -> ProspectusQueryObservation:
    evidence = audit.evidence
    trace = audit.trace
    if evidence is not None:
        return ProspectusQueryObservation(
            source_audit_id=audit.audit_id,
            source_audit_version=audit.audit_version,
            observed_at=audit.audited_at,
            security_response_sha256=evidence.security_response_sha256,
            announcement_response_sha256=evidence.announcement_response_sha256,
            outcome=QueryOutcome.FOUND,
            announcement_id=evidence.announcement_id,
            pdf_sha256=evidence.pdf_sha256,
        )
    if (
        audit.status is BridgeStatus.MISSING
        and audit.failure_reason == "final_prospectus_missing"
        and trace is not None
        and trace.org_id is not None
        and trace.announcement_response_sha256 is not None
    ):
        return ProspectusQueryObservation(
            source_audit_id=audit.audit_id,
            source_audit_version=audit.audit_version,
            observed_at=audit.audited_at,
            security_response_sha256=trace.security_response_sha256,
            announcement_response_sha256=trace.announcement_response_sha256,
            outcome=QueryOutcome.EMPTY,
            announcement_id=None,
            pdf_sha256=None,
        )
    detail = "source audit lacks comparable query evidence"
    raise ProspectusConsistencyError(detail)


def _org_id(audit: CninfoProspectusBridgeAudit) -> str:
    if audit.evidence is not None:
        return audit.evidence.org_id
    if audit.trace is not None and audit.trace.org_id is not None:
        return audit.trace.org_id
    detail = "source audit lacks provider organization identity"
    raise ProspectusConsistencyError(detail)


def _classify(
    observations: tuple[ProspectusQueryObservation, ...],
) -> tuple[ConsistencyStatus, str | None]:
    outcomes = {observation.outcome for observation in observations}
    if len(outcomes) != 1:
        return ConsistencyStatus.UNSTABLE, "query_outcome_changed"
    if observations[0].outcome is QueryOutcome.FOUND:
        documents = {(item.announcement_id, item.pdf_sha256) for item in observations}
        if len(documents) != 1:
            return ConsistencyStatus.UNSTABLE, "selected_document_changed"
    else:
        hashes = {item.announcement_response_sha256 for item in observations}
        if len(hashes) != 1:
            return ConsistencyStatus.UNSTABLE, "empty_response_changed"
    if len(observations) < _MINIMUM_OBSERVATIONS:
        return ConsistencyStatus.INSUFFICIENT, "minimum_observations_not_met"
    if observations[0].outcome is QueryOutcome.FOUND:
        return ConsistencyStatus.STABLE_FOUND, None
    return ConsistencyStatus.STABLE_EMPTY, None


def _query_spec(candidate: ProspectusBridgeCandidate, org_id: str) -> ProspectusQuerySpec:
    draft = ProspectusQuerySpec(
        query_id=f"cninfo_prospectus_query_{'0' * 64}",
        query_version=_QUERY_VERSION,
        code=candidate.symbol.split(".", maxsplit=1)[0],
        org_id=org_id,
        search_key="招股说明书",
        start_date=candidate.listing_date - timedelta(days=730),
        end_date=candidate.listing_date,
        page_size=50,
        tab_name="fulltext",
    )
    return draft.model_copy(
        update={"query_id": f"cninfo_prospectus_query_{_model_digest(draft, 'query_id')}"}
    )


def _sort_key(observation: ProspectusQueryObservation) -> tuple[datetime, str]:
    return observation.observed_at, observation.source_audit_id


def _model_digest(model: BaseModel, identity_field: str) -> str:
    encoded = json.dumps(
        model.model_dump(mode="json", exclude={identity_field}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
