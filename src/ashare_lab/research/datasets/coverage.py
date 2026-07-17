"""Cross-table point-in-time coverage qualification for dataset inputs."""

import hashlib
from collections.abc import Iterable

from ashare_lab.research.datasets.coverage_models import (
    ComponentCoverage,
    CoverageRequest,
    DatasetComponent,
    DatasetCoverageError,
    DatasetCoverageReport,
    DatasetInputManifest,
    QualificationStatus,
)

__all__ = [
    "ComponentCoverage",
    "CoverageRequest",
    "DatasetComponent",
    "DatasetCoverageError",
    "DatasetCoverageReport",
    "DatasetInputManifest",
    "QualificationStatus",
    "build_input_manifest",
    "qualify_dataset",
]


def qualify_dataset(
    request: CoverageRequest,
    components: tuple[ComponentCoverage, ...],
) -> DatasetCoverageReport:
    """Evaluate cross-table date, quality, PIT, and lineage evidence."""
    if request.start_date > request.end_date:
        detail = "coverage request start_date exceeds end_date"
        raise DatasetCoverageError(detail)
    required = tuple(sorted(set(request.required_components), key=lambda item: item.value))
    if not required:
        detail = "coverage request has no required components"
        raise DatasetCoverageError(detail)
    by_component = {component.component: component for component in components}
    if len(by_component) != len(components):
        detail = "coverage evidence contains duplicate components"
        raise DatasetCoverageError(detail)

    blockers: list[str] = []
    required_evidence: list[ComponentCoverage] = []
    for component_name in required:
        evidence = by_component.get(component_name)
        if evidence is None:
            blockers.append(f"{component_name.value}:missing_component")
            continue
        required_evidence.append(evidence)
        blockers.extend(_component_blockers(request, evidence))

    starts = tuple(
        evidence.start_date for evidence in required_evidence if evidence.start_date is not None
    )
    ends = tuple(
        evidence.end_date for evidence in required_evidence if evidence.end_date is not None
    )
    qualified_start = max(starts) if len(starts) == len(required) else None
    qualified_end = min(ends) if len(ends) == len(required) else None
    if (
        qualified_start is not None
        and qualified_end is not None
        and qualified_start > qualified_end
    ):
        blockers.append("common_interval:empty")
    normalized = tuple(sorted(components, key=lambda item: item.component.value))
    unique_blockers = tuple(sorted(set(blockers)))
    status = QualificationStatus.QUALIFIED if not unique_blockers else QualificationStatus.BLOCKED
    report_digest = hashlib.sha256(
        _report_identity(request, normalized, unique_blockers).encode()
    ).hexdigest()
    report_id = f"coverage_{report_digest}"
    return DatasetCoverageReport(
        report_id=report_id,
        request=CoverageRequest(request.start_date, request.end_date, required),
        status=status,
        qualified_start=qualified_start,
        qualified_end=qualified_end,
        components=normalized,
        blockers=unique_blockers,
    )


def build_input_manifest(report: DatasetCoverageReport) -> DatasetInputManifest:
    """Build a stable input manifest only from a qualified coverage report."""
    if report.status is not QualificationStatus.QUALIFIED:
        detail = "coverage report is not qualified"
        raise DatasetCoverageError(detail)
    required = set(report.request.required_components)
    components = tuple(
        component for component in report.components if component.component in required
    )
    schema_ids = _unique_sorted(
        identity for component in components for identity in component.schema_manifest_ids
    )
    snapshot_ids = _unique_sorted(
        identity for component in components for identity in component.source_snapshot_ids
    )
    lineage_ids = _unique_sorted(
        identity for component in components for identity in component.lineage_edge_ids
    )
    schema_manifest_id = f"schema_{_digest(schema_ids)}"
    lineage_manifest_id = f"lineage_{_digest(lineage_ids)}"
    identity = (
        report.report_id,
        schema_manifest_id,
        lineage_manifest_id,
        *schema_ids,
        *snapshot_ids,
        *lineage_ids,
    )
    return DatasetInputManifest(
        manifest_id=f"inputs_{_digest(identity)}",
        coverage_report_id=report.report_id,
        schema_manifest_id=schema_manifest_id,
        lineage_manifest_id=lineage_manifest_id,
        input_schema_manifest_ids=schema_ids,
        source_snapshot_ids=snapshot_ids,
        lineage_edge_ids=lineage_ids,
    )


def _component_blockers(
    request: CoverageRequest,
    evidence: ComponentCoverage,
) -> tuple[str, ...]:
    prefix = evidence.component.value
    blockers = [f"{prefix}:{blocker}" for blocker in evidence.blockers]
    if evidence.start_date is None or evidence.end_date is None:
        blockers.append(f"{prefix}:missing_date_coverage")
    else:
        if evidence.start_date > request.start_date:
            blockers.append(f"{prefix}:starts_after_request")
        if evidence.end_date < request.end_date:
            blockers.append(f"{prefix}:ends_before_request")
    if not evidence.schema_manifest_ids:
        blockers.append(f"{prefix}:missing_schema")
    if not evidence.source_snapshot_ids:
        blockers.append(f"{prefix}:missing_raw_snapshots")
    if not evidence.lineage_edge_ids:
        blockers.append(f"{prefix}:missing_lineage")
    if not evidence.quality_passed:
        blockers.append(f"{prefix}:quality_failed")
    if not evidence.point_in_time:
        blockers.append(f"{prefix}:not_point_in_time")
    return tuple(blockers)


def _report_identity(
    request: CoverageRequest,
    components: tuple[ComponentCoverage, ...],
    blockers: tuple[str, ...],
) -> str:
    component_identity = tuple(
        "|".join(
            (
                component.component.value,
                component.start_date.isoformat() if component.start_date else "null",
                component.end_date.isoformat() if component.end_date else "null",
                ",".join(component.schema_manifest_ids),
                ",".join(component.source_snapshot_ids),
                ",".join(component.lineage_edge_ids),
                str(component.quality_passed),
                str(component.point_in_time),
                ",".join(component.blockers),
            )
        )
        for component in components
    )
    return "|".join(
        (
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            ",".join(sorted(item.value for item in request.required_components)),
            *component_identity,
            *blockers,
        )
    )


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _digest(values: tuple[str, ...]) -> str:
    return hashlib.sha256("|".join(values).encode()).hexdigest()
