"""Immutable artifact persistence for historical industry source audits."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from ashare_lab.data.capco_industry_archives import CapcoIndustryArchiveAudit
from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.cninfo_industry_bridge import CninfoIndustryBridgeAudit
from ashare_lab.data.cninfo_observation_models import (
    CninfoProspectusConsistencyAudit,
)
from ashare_lab.data.cninfo_prospectus_bridge import CninfoProspectusBridgeAudit
from ashare_lab.data.historical_industry_admission_models import HistoricalIndustryAdmission
from ashare_lab.data.historical_industry_archives import HistoricalIndustryArchiveAudit
from ashare_lab.data.historical_industry_calendar import HistoricalIndustryCalendarEvidence
from ashare_lab.data.historical_industry_coverage_models import (
    HistoricalIndustryCoverageReport,
)
from ashare_lab.data.historical_industry_pilot_models import (
    PilotIndustryAdmission,
    PilotIndustryAdmissionBatch,
)
from ashare_lab.data.historical_industry_resolution_models import (
    HistoricalIndustryResolutionReport,
)
from ashare_lab.data.sse_industry_models import SseProspectusIndustryAudit


class ArchiveAuditArtifactError(Exception):
    """An existing audit artifact conflicts with the exact report bytes."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create an immutable source-audit storage failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the storage boundary and conflict detail."""
        return f"historical_industry_archive_artifact: {self.detail}"


@dataclass(frozen=True, slots=True)
class ArchiveAuditArtifact:
    """Filesystem location and identity of one source-only audit report."""

    audit_id: str
    path: Path


def write_archive_audit(
    report: HistoricalIndustryArchiveAudit,
    root: Path,
) -> ArchiveAuditArtifact:
    """Publish one report atomically or verify the existing immutable bytes."""
    return _write_document(report.audit_id, report.model_dump_json(indent=2), root)


def write_capco_archive_audit(
    report: CapcoIndustryArchiveAudit,
    root: Path,
) -> ArchiveAuditArtifact:
    """Publish one CAPCO report without granting research-data access."""
    return _write_document(report.audit_id, report.model_dump_json(indent=2), root)


def write_capco_membership_audit(
    report: CapcoMembershipAudit,
    root: Path,
) -> ArchiveAuditArtifact:
    """Publish one later CAPCO membership audit without research-data authority."""
    return _write_document(report.audit_id, report.model_dump_json(indent=2), root)


def write_cninfo_bridge_audit(
    report: CninfoIndustryBridgeAudit,
    root: Path,
) -> ArchiveAuditArtifact:
    """Publish one CNInfo bridge audit without changing market data."""
    return _write_document(report.audit_id, report.model_dump_json(indent=2), root)


def write_cninfo_prospectus_bridge_audit(
    report: CninfoProspectusBridgeAudit,
    root: Path,
) -> ArchiveAuditArtifact:
    """Publish one parent-linked prospectus supplement without market-data authority."""
    return _write_document(report.audit_id, report.model_dump_json(indent=2), root)


def write_cninfo_prospectus_consistency_audit(
    report: CninfoProspectusConsistencyAudit,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist a repeated-query conclusion without authorizing research use."""
    return _write_document(
        report.consistency_id,
        report.model_dump_json(indent=2),
        root,
    )


def write_sse_prospectus_industry_audit(
    report: SseProspectusIndustryAudit,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist exact independent SSE evidence without research-data authority."""
    return _write_document(report.audit_id, report.model_dump_json(indent=2), root)


def write_historical_industry_admission(
    report: HistoricalIndustryAdmission,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist one source-only admission without granting research-data access."""
    return _write_document(report.admission_id, report.model_dump_json(indent=2), root)


def write_historical_industry_calendar(
    report: HistoricalIndustryCalendarEvidence,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist exact calendar projection evidence as immutable source-only bytes."""
    return _write_document(
        report.calendar_artifact_id,
        report.model_dump_json(indent=2),
        root,
    )


def write_historical_industry_resolution(
    report: HistoricalIndustryResolutionReport,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist one all-candidate source decision without research authority."""
    return _write_document(report.resolution_id, report.model_dump_json(indent=2), root)


def write_historical_industry_pilot_admission(
    report: PilotIndustryAdmission,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist one resolved pilot admission without research authority."""
    return _write_document(report.admission_id, report.model_dump_json(indent=2), root)


def write_historical_industry_admission_batch(
    report: PilotIndustryAdmissionBatch,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist exact all-candidate source-only admission coverage."""
    return _write_document(report.batch_id, report.model_dump_json(indent=2), root)


def write_historical_industry_coverage_report(
    report: HistoricalIndustryCoverageReport,
    root: Path,
) -> ArchiveAuditArtifact:
    """Persist an immutable coverage decision without research-data authority."""
    return _write_document(report.report_id, report.model_dump_json(indent=2), root)


def _write_document(audit_id: str, document_json: str, root: Path) -> ArchiveAuditArtifact:
    """Write exact source-audit JSON under its precomputed identity."""
    content = f"{document_json}\n".encode()
    directory = root / audit_id
    path = directory / "manifest.json"
    descriptor = ArchiveAuditArtifact(audit_id=audit_id, path=path)
    if directory.exists():
        try:
            with path.open("rb") as stream:
                existing = stream.read()
        except OSError as error:
            detail = "cannot read existing manifest"
            raise ArchiveAuditArtifactError(detail) from error
        if existing != content:
            detail = "existing manifest bytes differ"
            raise ArchiveAuditArtifactError(detail)
        return descriptor
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".tmp-", dir=root) as temporary_name:
        temporary = Path(temporary_name)
        with (temporary / "manifest.json").open("wb") as stream:
            stream.write(content)
        temporary.replace(directory)
    return descriptor
