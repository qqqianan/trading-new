"""Immutable persistence for full CNInfo discovery plans and shards."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from ashare_lab.data.cninfo_listing_discovery import CninfoListingDiscoveryAudit
from ashare_lab.services.cninfo_discovery_coverage import CninfoDiscoveryCoverage
from ashare_lab.services.cninfo_full_discovery import (
    CninfoFullDiscoveryPlan,
    CninfoFullDiscoveryShard,
)


class CninfoFullDiscoveryArtifactError(Exception):
    """An existing discovery artifact conflicts with exact report bytes."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one immutable storage failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the artifact boundary and reason."""
        return f"cninfo_full_discovery_artifact: {self.detail}"


@dataclass(frozen=True, slots=True)
class CninfoFullDiscoveryArtifact:
    """Filesystem identity of one immutable discovery document."""

    artifact_id: str
    path: Path


def write_discovery_coverage(
    report: CninfoDiscoveryCoverage,
    root: Path,
) -> CninfoFullDiscoveryArtifact:
    """Persist verified full-population discovery coverage without granting research use."""
    return _write_document(report.report_id, report.model_dump_json(indent=2), root)


def write_full_discovery_plan(
    plan: CninfoFullDiscoveryPlan,
    root: Path,
) -> CninfoFullDiscoveryArtifact:
    """Persist a pre-network full-population discovery plan."""
    return _write_document(plan.plan_id, plan.model_dump_json(indent=2), root)


def write_listing_discovery_audit(
    audit: CninfoListingDiscoveryAudit,
    root: Path,
) -> CninfoFullDiscoveryArtifact:
    """Persist one selected or failed listing discovery observation."""
    return _write_document(audit.audit_id, audit.model_dump_json(indent=2), root)


def write_full_discovery_shard(
    shard: CninfoFullDiscoveryShard,
    root: Path,
) -> CninfoFullDiscoveryArtifact:
    """Persist one exact completed recovery unit."""
    return _write_document(shard.shard_id, shard.model_dump_json(indent=2), root)


def _write_document(
    artifact_id: str,
    document_json: str,
    root: Path,
) -> CninfoFullDiscoveryArtifact:
    content = f"{document_json}\n".encode()
    directory = root / artifact_id
    path = directory / "manifest.json"
    artifact = CninfoFullDiscoveryArtifact(artifact_id=artifact_id, path=path)
    if directory.exists():
        try:
            with path.open("rb") as stream:
                existing = stream.read()
        except OSError as error:
            detail = "cannot read existing manifest"
            raise CninfoFullDiscoveryArtifactError(detail) from error
        if existing != content:
            detail = "existing manifest bytes differ"
            raise CninfoFullDiscoveryArtifactError(detail)
        return artifact
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".tmp-", dir=root) as temporary_name:
        temporary = Path(temporary_name)
        with (temporary / "manifest.json").open("wb") as stream:
            stream.write(content)
        temporary.replace(directory)
    return artifact
