from datetime import date

import pytest

from ashare_lab.research.datasets.batch_coverage import (
    BatchCoverageSpec,
    BatchObservation,
    GovernedBatchEvidence,
    audit_dated_batches,
)
from ashare_lab.research.datasets.coverage import DatasetComponent


def _evidence(snapshot_id: str, endpoint: str) -> GovernedBatchEvidence:
    return GovernedBatchEvidence(
        snapshot_id=snapshot_id,
        endpoint=endpoint,
        schema_manifest_id="schema_market",
        status="ACCEPTED",
        versioned_lineage_edge_ids=(f"lineage_{snapshot_id}",),
        qualified_lineage_edge_ids=(f"lineage_{snapshot_id}",),
    )


def test_dated_batch_audit_accepts_every_endpoint_on_every_required_date() -> None:
    # Given: two open dates with a complete calendar and five-endpoint market bundle.
    dates = (date(2020, 1, 2), date(2020, 1, 3))
    endpoints = ("trade_cal", "daily", "adj_factor")
    observations = tuple(
        BatchObservation(day, endpoint, f"snap_{day:%Y%m%d}_{endpoint}")
        for day in dates
        for endpoint in endpoints
    )
    evidence = tuple(
        _evidence(observation.snapshot_id, observation.endpoint) for observation in observations
    )

    # When: batch-level governance is audited without sampling dates.
    coverage = audit_dated_batches(
        BatchCoverageSpec(
            DatasetComponent.MARKET_DAILY,
            dates,
            endpoints,
            "schema_market",
        ),
        observations,
        evidence,
    )

    # Then: the exact common interval and every immutable identity are retained.
    assert coverage.start_date == dates[0]
    assert coverage.end_date == dates[-1]
    assert len(coverage.source_snapshot_ids) == 6
    assert len(coverage.lineage_edge_ids) == 6
    assert coverage.blockers == ()


def test_dated_batch_audit_blocks_internal_gaps_and_unversioned_evidence() -> None:
    # Given: one date missing suspension evidence and another with old unversioned lineage.
    dates = (date(2020, 1, 2), date(2020, 1, 3))
    observations = (
        BatchObservation(dates[0], "daily", "snap_daily_1"),
        BatchObservation(dates[0], "suspend_d", "snap_suspend_1"),
        BatchObservation(dates[1], "daily", "snap_daily_2"),
    )
    evidence = (
        _evidence("snap_daily_1", "daily"),
        _evidence("snap_suspend_1", "suspend_d"),
        GovernedBatchEvidence(
            "snap_daily_2",
            "daily",
            "schema_market",
            "ACCEPTED",
            (),
            (),
        ),
    )

    # When: the requested schedule is audited.
    coverage = audit_dated_batches(
        BatchCoverageSpec(
            DatasetComponent.MARKET_DAILY,
            dates,
            ("daily", "suspend_d"),
            "schema_market",
        ),
        observations,
        evidence,
    )

    # Then: envelope dates cannot hide either the gap or unversioned lineage.
    assert coverage.end_date == dates[0]
    assert coverage.quality_passed is False
    assert coverage.point_in_time is False
    assert coverage.blockers == ("missing_scheduled_dates", "unversioned_lineage")


@pytest.mark.parametrize(
    ("evidence", "blocker"),
    [
        ((), "missing_raw_snapshot"),
        (
            (
                GovernedBatchEvidence(
                    "snap_001",
                    "daily",
                    "wrong_schema",
                    "ACCEPTED",
                    ("lineage_001",),
                    ("lineage_001",),
                ),
            ),
            "schema_mismatch",
        ),
        (
            (
                GovernedBatchEvidence(
                    "snap_001",
                    "daily",
                    "schema_market",
                    "ACCEPTED",
                    ("lineage_001",),
                    (),
                ),
            ),
            "missing_quality",
        ),
    ],
)
def test_dated_batch_audit_names_each_failed_governance_boundary(
    evidence: tuple[GovernedBatchEvidence, ...],
    blocker: str,
) -> None:
    # Given: one scheduled response failing one exact governance boundary.
    observation = BatchObservation(date(2020, 1, 2), "daily", "snap_001")

    # When: the daily evidence is audited.
    coverage = audit_dated_batches(
        BatchCoverageSpec(
            DatasetComponent.MARKET_DAILY,
            (date(2020, 1, 2),),
            ("daily",),
            "schema_market",
        ),
        (observation,),
        evidence,
    )

    # Then: the component fails closed with the stable boundary reason.
    assert blocker in coverage.blockers
