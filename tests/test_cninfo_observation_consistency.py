from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ashare_lab.data.cninfo_observation_consistency import build_prospectus_consistency_audit
from ashare_lab.data.cninfo_observation_models import (
    ConsistencyStatus,
    ProspectusConsistencyError,
)
from ashare_lab.data.cninfo_prospectus_bridge import ProspectusBridgeCandidate
from ashare_lab.data.historical_industry_artifacts import (
    write_cninfo_prospectus_consistency_audit,
)

from .cninfo_prospectus_fixtures import prospectus_audit


def test_consistency_is_unstable_when_same_query_changes_outcome() -> None:
    # Given: one successful observation and one empty response for the same query.
    candidate = _candidate()
    found = prospectus_audit(candidate, observed_at=_observed_at(0), found=True, marker="a")
    empty = prospectus_audit(candidate, observed_at=_observed_at(1), found=False, marker="b")

    # When: the exact observations are assessed together.
    report = build_prospectus_consistency_audit(
        candidate,
        (found, empty),
        assessed_at=_observed_at(2),
    )

    # Then: a prior success cannot hide the provider inconsistency.
    assert report.status is ConsistencyStatus.UNSTABLE
    assert report.reason == "query_outcome_changed"
    assert report.research_use_authorized is False


def test_consistency_requires_three_matching_observations() -> None:
    # Given: only two identical successful observations.
    candidate = _candidate()
    audits = tuple(
        prospectus_audit(candidate, observed_at=_observed_at(index), found=True, marker="a")
        for index in range(2)
    )

    # When: the observations are assessed before the minimum is met.
    report = build_prospectus_consistency_audit(
        candidate,
        audits,
        assessed_at=_observed_at(2),
    )

    # Then: repeated success remains insufficient rather than accepted.
    assert report.status is ConsistencyStatus.INSUFFICIENT
    assert report.reason == "minimum_observations_not_met"


def test_consistency_accepts_three_identical_selected_documents() -> None:
    # Given: three observations select the same official announcement and PDF.
    candidate = _candidate()
    audits = tuple(
        prospectus_audit(candidate, observed_at=_observed_at(index), found=True, marker="a")
        for index in range(3)
    )

    # When: the complete observation set is assessed.
    report = build_prospectus_consistency_audit(
        candidate,
        audits,
        assessed_at=_observed_at(3),
    )

    # Then: the source is stable but still has no research-data authority.
    assert report.status is ConsistencyStatus.STABLE_FOUND
    assert report.reason is None
    assert report.stable_announcement_id == "1211660704"
    assert report.research_use_authorized is False


def test_consistency_report_is_persisted_under_its_content_identity(tmp_path: Path) -> None:
    # Given: an unstable report retaining both success and empty observations.
    candidate = _candidate()
    report = build_prospectus_consistency_audit(
        candidate,
        (
            prospectus_audit(candidate, observed_at=_observed_at(0), found=True, marker="a"),
            prospectus_audit(candidate, observed_at=_observed_at(1), found=False, marker="b"),
        ),
        assessed_at=_observed_at(2),
    )

    # When: the source-only evidence is published.
    artifact = write_cninfo_prospectus_consistency_audit(report, tmp_path)

    # Then: its directory is the precomputed immutable identity.
    assert artifact.path == tmp_path / report.consistency_id / "manifest.json"


def test_consistency_rejects_an_unregistered_query_semantics_version() -> None:
    # Given: a future source audit version with no declared query compatibility.
    candidate = _candidate()
    future = prospectus_audit(
        candidate,
        observed_at=_observed_at(0),
        found=True,
        marker="a",
    ).model_copy(update={"audit_version": "cninfo_prospectus_bridge_audit_v99"})

    # When / Then: the protocol refuses to infer that its query was unchanged.
    with pytest.raises(ProspectusConsistencyError, match="query semantics"):
        build_prospectus_consistency_audit(
            candidate,
            (future,),
            assessed_at=_observed_at(1),
        )


def test_consistency_accepts_three_identical_empty_responses() -> None:
    # Given: three exact empty provider responses for the same natural query.
    candidate = _candidate()
    audits = tuple(
        prospectus_audit(candidate, observed_at=_observed_at(index), found=False, marker="a")
        for index in range(3)
    )

    # When: the minimum observation set is assessed.
    report = build_prospectus_consistency_audit(
        candidate,
        audits,
        assessed_at=_observed_at(3),
    )

    # Then: absence is stable without becoming positive industry evidence.
    assert report.status is ConsistencyStatus.STABLE_EMPTY
    assert report.stable_announcement_id is None


def test_consistency_is_unstable_when_selected_document_changes() -> None:
    # Given: repeated success observations selecting different announcement IDs.
    candidate = _candidate()
    first = prospectus_audit(candidate, observed_at=_observed_at(0), found=True, marker="a")
    second = prospectus_audit(candidate, observed_at=_observed_at(1), found=True, marker="b")
    assert second.evidence is not None
    changed = second.model_copy(
        update={"evidence": second.evidence.model_copy(update={"announcement_id": "1211660705"})}
    )

    # When: both successful observations are assessed.
    report = build_prospectus_consistency_audit(
        candidate,
        (first, changed),
        assessed_at=_observed_at(2),
    )

    # Then: the protocol rejects the changing document selection.
    assert report.status is ConsistencyStatus.UNSTABLE
    assert report.reason == "selected_document_changed"


def test_consistency_rejects_a_source_audit_without_comparable_trace() -> None:
    # Given: a legacy empty audit that did not retain its query response trace.
    candidate = _candidate()
    legacy = prospectus_audit(
        candidate,
        observed_at=_observed_at(0),
        found=False,
        marker="a",
    ).model_copy(update={"audit_version": "cninfo_prospectus_bridge_audit_v3", "trace": None})

    # When / Then: incomplete evidence cannot enter a consistency report.
    with pytest.raises(ProspectusConsistencyError, match="comparable query evidence"):
        build_prospectus_consistency_audit(
            candidate,
            (legacy,),
            assessed_at=_observed_at(1),
        )


def test_consistency_rejects_an_empty_observation_set() -> None:
    # Given: a candidate without any retained source observation.
    candidate = _candidate()

    # When / Then: absence of evidence cannot produce a consistency conclusion.
    with pytest.raises(ProspectusConsistencyError, match="at least one"):
        build_prospectus_consistency_audit(
            candidate,
            (),
            assessed_at=_observed_at(0),
        )


def test_consistency_rejects_an_observation_for_another_candidate() -> None:
    # Given: a source observation linked to a different parent candidate.
    candidate = _candidate()
    other = candidate.model_copy(update={"symbol": "001230.SZ"})
    audit = prospectus_audit(other, observed_at=_observed_at(0), found=True, marker="a")

    # When / Then: cross-candidate evidence cannot be compared.
    with pytest.raises(ProspectusConsistencyError, match="candidate differs"):
        build_prospectus_consistency_audit(
            candidate,
            (audit,),
            assessed_at=_observed_at(1),
        )


def _candidate() -> ProspectusBridgeCandidate:
    return ProspectusBridgeCandidate(
        parent_audit_id=f"cninfo_industry_bridge_audit_{'a' * 64}",
        symbol="688190.SH",
        listing_date=date(2021, 11, 26),
    )


def _observed_at(index: int) -> datetime:
    return datetime(2026, 7, 27, 9, tzinfo=UTC) + timedelta(minutes=index)
