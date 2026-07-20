"""Composition root for the complete real development factor report."""

import hashlib
from pathlib import Path

from ashare_lab.research.artifacts.models import ResearchArtifactError
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
    DatasetSpecStoreError,
)
from ashare_lab.research.experiments.trial_ledger import TrialLedgerError, TrialLedgerStore
from ashare_lab.research.experiments.trial_models import TrialBatchDescriptor
from ashare_lab.research.factors.diagnostics import FactorDiagnosticError
from ashare_lab.research.factors.report_store import (
    FactorReportDescriptor,
    FactorReportStore,
    FactorReportStoreError,
)
from ashare_lab.research.factors.runtime_frames import DiagnosticFrameAssemblyError
from ashare_lab.research.factors.runtime_source import (
    ArtifactFactorFrameSource,
    FactorRuntimeSourceError,
    VerifiedArtifactFrameReader,
)
from ashare_lab.research.factors.selection import FactorSelectionError
from ashare_lab.research.factors.service import AuditedFactorResearchService
from ashare_lab.research.preprocessing.fold import FoldPreprocessingError
from ashare_lab.research.splits.walk_forward import SplitIntegrityError
from ashare_lab.services.factor_calendar_runtime import (
    FactorCalendarRuntimeError,
    load_dataset_development_calendar,
)


class FactorDiagnosticRuntimeError(Exception):
    """Real frozen artifacts cannot complete the audited diagnostic stage."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable composition-root failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"factor_diagnostic_runtime: {self.detail}"


def run_default_factor_diagnostics(project_root: Path) -> FactorReportDescriptor:
    """Verify the sole DatasetSpec and trial batch, then publish all diagnostics."""
    artifact_root = project_root / "data" / "artifacts"
    try:
        dataset_path = _sole_path(
            artifact_root / "dataset_spec",
            "ds_*/manifest.json",
            "DatasetSpec",
        )
        trial_path = _sole_path(
            artifact_root / "trial_ledger",
            "trial_batch_*/manifest.json",
            "trial batch",
        )
        dataset_descriptor = DatasetSpecDescriptor(
            snapshot_id=dataset_path.parent.name,
            manifest_path=dataset_path,
            data_sha256=_sha256(dataset_path),
        )
        spec = DatasetSpecStore(artifact_root).read(dataset_descriptor)
        trial_descriptor = TrialBatchDescriptor(
            batch_id=trial_path.parent.name,
            manifest_path=trial_path,
            data_sha256=_sha256(trial_path),
        )
        ledger = TrialLedgerStore(artifact_root)
        calendar = load_dataset_development_calendar(project_root, spec)
        report = AuditedFactorResearchService(ledger).run_streaming(
            trial_descriptor,
            ArtifactFactorFrameSource(
                VerifiedArtifactFrameReader(project_root),
                spec,
                calendar,
            ),
        )
        return FactorReportStore(artifact_root).write(report)
    except (
        DatasetSpecStoreError,
        TrialLedgerError,
        ResearchArtifactError,
        FactorRuntimeSourceError,
        DiagnosticFrameAssemblyError,
        FoldPreprocessingError,
        SplitIntegrityError,
        FactorDiagnosticError,
        FactorSelectionError,
        FactorReportStoreError,
        FactorCalendarRuntimeError,
    ) as error:
        raise FactorDiagnosticRuntimeError(str(error)) from error


def _sole_path(root: Path, pattern: str, label: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one {label}, found {len(paths)}"
        raise FactorDiagnosticRuntimeError(detail)
    return paths[0]


def _sha256(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        detail = f"artifact manifest cannot be read: {path}"
        raise FactorDiagnosticRuntimeError(detail) from error
    return hashlib.sha256(content).hexdigest()
