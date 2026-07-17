"""Application service for evidence-derived dataset qualification."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ashare_lab.research.datasets.artifact_store import DatasetArtifactWriteResult
from ashare_lab.research.datasets.coverage import (
    ComponentCoverage,
    CoverageRequest,
    DatasetCoverageReport,
    DatasetInputManifest,
    QualificationStatus,
    build_input_manifest,
    qualify_dataset,
)


class CoverageEvidenceReader(Protocol):
    """Capability that derives component facts from governed storage."""

    def components(self, request: CoverageRequest) -> tuple[ComponentCoverage, ...]:
        """Read the exact evidence matrix for one request."""
        ...


class CoverageArtifactSink(Protocol):
    """Append-only boundary for qualification reports and manifests."""

    def write(
        self,
        report: DatasetCoverageReport,
        manifest: DatasetInputManifest | None,
        recorded_at: datetime,
    ) -> DatasetArtifactWriteResult:
        """Persist one complete qualification decision."""
        ...


@dataclass(frozen=True, slots=True)
class DatasetCoverageRun:
    """Observable result from one persisted qualification attempt."""

    report: DatasetCoverageReport
    manifest: DatasetInputManifest | None
    write_result: DatasetArtifactWriteResult


class DatasetCoverageService:
    """Keep evidence reading, pure adjudication, and persistence in fixed order."""

    def __init__(self, reader: CoverageEvidenceReader, sink: CoverageArtifactSink) -> None:
        """Bind mandatory facts and append-only persistence."""
        self._reader = reader
        self._sink = sink

    def qualify(self, request: CoverageRequest, recorded_at: datetime) -> DatasetCoverageRun:
        """Persist a report and only create a manifest when qualification passes."""
        report = qualify_dataset(request, self._reader.components(request))
        match report.status:
            case QualificationStatus.QUALIFIED:
                manifest = build_input_manifest(report)
            case QualificationStatus.BLOCKED:
                manifest = None
        written = self._sink.write(report, manifest, recorded_at)
        return DatasetCoverageRun(report, manifest, written)
