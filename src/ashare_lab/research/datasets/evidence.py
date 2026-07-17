"""Pure audit of Raw-to-PIT evidence used by dataset qualification."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class ArtifactEvidence:
    """One candidate canonical or PIT artifact projected from Mongo."""

    artifact_id: str
    source_snapshot_id: str
    input_schema_manifest_id: str
    schema_manifest_id: str
    quality_report_id: str
    quality_status: str
    available_at: datetime


@dataclass(frozen=True, slots=True)
class SnapshotEvidence:
    """Raw source status and exact schema identity."""

    snapshot_id: str
    schema_manifest_id: str
    status: str


@dataclass(frozen=True, slots=True)
class QualityEvidence:
    """Quality decision bound to one exact artifact."""

    quality_report_id: str
    artifact_id: str
    passed: bool


@dataclass(frozen=True, slots=True)
class LineageEvidence:
    """Field-level transformation edge with reproducible code identity."""

    lineage_edge_id: str
    upstream_artifact_id: str
    downstream_artifact_id: str
    output_schema_id: str
    code_commit: str


@dataclass(frozen=True, slots=True)
class ArtifactEvidenceAudit:
    """Normalized identities and blockers consumed by component coverage."""

    schema_manifest_ids: tuple[str, ...]
    source_snapshot_ids: tuple[str, ...]
    lineage_edge_ids: tuple[str, ...]
    quality_passed: bool
    point_in_time: bool
    blockers: tuple[str, ...]


def audit_artifact_evidence(
    artifacts: tuple[ArtifactEvidence, ...],
    snapshots: tuple[SnapshotEvidence, ...],
    quality_reports: tuple[QualityEvidence, ...],
    lineage_edges: tuple[LineageEvidence, ...],
) -> ArtifactEvidenceAudit:
    """Fail closed unless every artifact has a versioned Raw-quality-lineage chain."""
    blockers: set[str] = set()
    if not artifacts:
        blockers.add("empty_artifact_evidence")
    snapshots_by_id = {item.snapshot_id: item for item in snapshots}
    quality_by_id = {item.quality_report_id: item for item in quality_reports}
    lineage_by_artifact: dict[str, list[LineageEvidence]] = {}
    for edge in lineage_edges:
        lineage_by_artifact.setdefault(edge.downstream_artifact_id, []).append(edge)

    accepted_sources: set[str] = set()
    accepted_lineage: set[str] = set()
    quality_passed = bool(artifacts)
    point_in_time = bool(artifacts)
    for artifact in artifacts:
        if artifact.quality_status != "ACCEPTED":
            blockers.add("artifact_not_accepted")
            quality_passed = False
        if artifact.available_at.tzinfo is None or artifact.available_at.utcoffset() is None:
            blockers.add("missing_available_at")
            point_in_time = False
        source_id = _accepted_source(artifact, snapshots_by_id)
        if source_id is None:
            blockers.add("missing_raw_snapshot")
        else:
            accepted_sources.add(source_id)
        quality_blocker = _quality_blocker(artifact, quality_by_id)
        if quality_blocker is not None:
            blockers.add(quality_blocker)
            quality_passed = False
        lineage_ids, lineage_blocker = _accepted_lineage(
            artifact,
            tuple(lineage_by_artifact.get(artifact.artifact_id, ())),
        )
        accepted_lineage.update(lineage_ids)
        if lineage_blocker is not None:
            blockers.add(lineage_blocker)

    return ArtifactEvidenceAudit(
        schema_manifest_ids=tuple(sorted({item.schema_manifest_id for item in artifacts})),
        source_snapshot_ids=tuple(sorted(accepted_sources)),
        lineage_edge_ids=tuple(sorted(accepted_lineage)),
        quality_passed=quality_passed,
        point_in_time=point_in_time,
        blockers=tuple(sorted(blockers)),
    )


def _accepted_source(
    artifact: ArtifactEvidence,
    snapshots_by_id: dict[str, SnapshotEvidence],
) -> str | None:
    snapshot = snapshots_by_id.get(artifact.source_snapshot_id)
    if (
        snapshot is None
        or snapshot.status != "ACCEPTED"
        or snapshot.schema_manifest_id != artifact.input_schema_manifest_id
    ):
        return None
    return snapshot.snapshot_id


def _quality_blocker(
    artifact: ArtifactEvidence,
    quality_by_id: dict[str, QualityEvidence],
) -> str | None:
    quality = quality_by_id.get(artifact.quality_report_id)
    if quality is None or quality.artifact_id != artifact.artifact_id:
        return "missing_quality"
    if not quality.passed:
        return "quality_failed"
    return None


def _accepted_lineage(
    artifact: ArtifactEvidence,
    edges: tuple[LineageEvidence, ...],
) -> tuple[tuple[str, ...], str | None]:
    matching = tuple(
        edge
        for edge in edges
        if edge.upstream_artifact_id == artifact.source_snapshot_id
        and edge.output_schema_id == artifact.schema_manifest_id
    )
    if not matching:
        return (), "missing_lineage"
    versioned = tuple(edge for edge in matching if _COMMIT_PATTERN.fullmatch(edge.code_commit))
    if not versioned:
        return (), "unversioned_lineage"
    return tuple(edge.lineage_edge_id for edge in versioned), None
