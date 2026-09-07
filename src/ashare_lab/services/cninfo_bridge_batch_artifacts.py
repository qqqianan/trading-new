"""Immutable filesystem persistence for CNInfo bridge batch audits."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from ashare_lab.services.cninfo_bridge_batch import CninfoBridgeBatchAudit
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection
from ashare_lab.services.cninfo_prospectus_batch import CninfoProspectusBatchAudit


class CninfoBridgeBatchArtifactError(Exception):
    """An existing batch artifact conflicts with the exact report bytes."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one immutable batch storage failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the storage boundary and conflict detail."""
        return f"cninfo_bridge_batch_artifact: {self.detail}"


@dataclass(frozen=True, slots=True)
class CninfoBridgeBatchArtifact:
    """Filesystem identity of one source-only batch report."""

    batch_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class CninfoBridgeSelectionArtifact:
    """Filesystem identity of one preregistered candidate selection."""

    selection_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class CninfoProspectusBatchArtifact:
    """Filesystem identity of one parent-linked supplemental batch."""

    batch_id: str
    path: Path


def write_cninfo_bridge_selection(
    selection: StratifiedCandidateSelection,
    root: Path,
) -> CninfoBridgeSelectionArtifact:
    """Persist the fixed selection before any outcome-dependent audit runs."""
    path = _write_document(
        selection.selection_id,
        selection.model_dump_json(indent=2),
        root,
    )
    return CninfoBridgeSelectionArtifact(selection.selection_id, path)


def write_cninfo_bridge_batch(
    report: CninfoBridgeBatchAudit,
    root: Path,
) -> CninfoBridgeBatchArtifact:
    """Publish exact batch JSON atomically or verify immutable existing bytes."""
    path = _write_document(report.batch_id, report.model_dump_json(indent=2), root)
    return CninfoBridgeBatchArtifact(batch_id=report.batch_id, path=path)


def write_cninfo_prospectus_batch(
    report: CninfoProspectusBatchAudit,
    root: Path,
) -> CninfoProspectusBatchArtifact:
    """Publish one exact supplemental batch under its content identity."""
    path = _write_document(report.batch_id, report.model_dump_json(indent=2), root)
    return CninfoProspectusBatchArtifact(batch_id=report.batch_id, path=path)


def _write_document(artifact_id: str, document_json: str, root: Path) -> Path:
    content = f"{document_json}\n".encode()
    directory = root / artifact_id
    path = directory / "manifest.json"
    if directory.exists():
        try:
            with path.open("rb") as stream:
                existing = stream.read()
        except OSError as error:
            detail = "cannot read existing manifest"
            raise CninfoBridgeBatchArtifactError(detail) from error
        if existing != content:
            detail = "existing manifest bytes differ"
            raise CninfoBridgeBatchArtifactError(detail)
        return path
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".tmp-", dir=root) as temporary_name:
        temporary = Path(temporary_name)
        with (temporary / "manifest.json").open("wb") as stream:
            stream.write(content)
        temporary.replace(directory)
    return path
