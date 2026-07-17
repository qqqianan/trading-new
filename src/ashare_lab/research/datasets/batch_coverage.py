"""Pure batch-level governance audit for scheduled market observations."""

from dataclasses import dataclass
from datetime import date

from ashare_lab.research.datasets.coverage_models import ComponentCoverage, DatasetComponent


@dataclass(frozen=True, slots=True)
class BatchObservation:
    """One endpoint observation assigned to one required trading date."""

    trading_date: date
    endpoint: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class GovernedBatchEvidence:
    """Normalized Raw-to-canonical evidence for one provider response."""

    snapshot_id: str
    endpoint: str
    schema_manifest_id: str
    status: str
    versioned_lineage_edge_ids: tuple[str, ...]
    qualified_lineage_edge_ids: tuple[str, ...]
    qualified_artifact_ids: tuple[str, ...] = ()
    quality_evidenced_artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchCoverageSpec:
    """Closed schedule and schema contract for one dataset component."""

    component: DatasetComponent
    required_dates: tuple[date, ...]
    required_endpoints: tuple[str, ...]
    schema_manifest_id: str


def audit_dated_batches(
    spec: BatchCoverageSpec,
    observations: tuple[BatchObservation, ...],
    evidence: tuple[GovernedBatchEvidence, ...],
) -> ComponentCoverage:
    """Require a qualified response for every endpoint on every scheduled date."""
    evidence_by_id = {item.snapshot_id: item for item in evidence}
    observations_by_key: dict[tuple[date, str], list[BatchObservation]] = {}
    for observation in observations:
        observations_by_key.setdefault((observation.trading_date, observation.endpoint), []).append(
            observation
        )

    blockers: set[str] = set()
    complete_dates: list[date] = []
    selected_snapshots: set[str] = set()
    selected_lineage: set[str] = set()
    if not spec.required_dates:
        blockers.add("empty_scheduled_dates")
    for trading_date in spec.required_dates:
        date_complete = True
        for endpoint in spec.required_endpoints:
            selected, failure = _select_batch(
                tuple(observations_by_key.get((trading_date, endpoint), ())),
                evidence_by_id,
                spec.schema_manifest_id,
            )
            if selected is None:
                date_complete = False
                blockers.update(failure)
                continue
            selected_snapshots.add(selected.snapshot_id)
            selected_lineage.update(selected.qualified_lineage_edge_ids)
        if date_complete:
            complete_dates.append(trading_date)
    if len(complete_dates) != len(spec.required_dates):
        blockers.add("missing_scheduled_dates")
    normalized_blockers = tuple(sorted(blockers))
    passed = not normalized_blockers
    return ComponentCoverage(
        component=spec.component,
        start_date=min(complete_dates) if complete_dates else None,
        end_date=max(complete_dates) if complete_dates else None,
        schema_manifest_ids=(spec.schema_manifest_id,),
        source_snapshot_ids=tuple(sorted(selected_snapshots)),
        lineage_edge_ids=tuple(sorted(selected_lineage)),
        quality_passed=passed,
        point_in_time=passed,
        blockers=normalized_blockers,
    )


def _select_batch(
    observations: tuple[BatchObservation, ...],
    evidence_by_id: dict[str, GovernedBatchEvidence],
    schema_manifest_id: str,
) -> tuple[GovernedBatchEvidence | None, tuple[str, ...]]:
    failures: set[str] = set()
    for observation in sorted(observations, key=lambda item: item.snapshot_id):
        batch = evidence_by_id.get(observation.snapshot_id)
        if batch is None or batch.status != "ACCEPTED":
            failures.add("missing_raw_snapshot")
            continue
        if batch.schema_manifest_id != schema_manifest_id:
            failures.add("schema_mismatch")
            continue
        if not batch.versioned_lineage_edge_ids:
            failures.add("unversioned_lineage")
            continue
        if not batch.qualified_lineage_edge_ids:
            failures.add("missing_quality")
            continue
        return batch, ()
    return None, tuple(sorted(failures))
