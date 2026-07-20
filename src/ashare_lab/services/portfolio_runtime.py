"""Composition root for real development portfolio target publication."""

import hashlib
from pathlib import Path

from pydantic import ValidationError

from ashare_lab.portfolio.builder import PortfolioConstructionError
from ashare_lab.portfolio.research_store import (
    PortfolioTargetDescriptor,
    PortfolioTargetStore,
    PortfolioTargetStoreError,
)
from ashare_lab.research.artifacts.models import ResearchArtifactError
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
    DatasetSpecStoreError,
)
from ashare_lab.research.experiments.trial_ledger import TrialLedgerError, TrialLedgerStore
from ashare_lab.research.experiments.trial_models import TrialBatchDescriptor
from ashare_lab.research.factors.report_store import (
    FactorReportDescriptor,
    FactorReportStore,
    FactorReportStoreError,
)
from ashare_lab.research.factors.runtime_frames import DiagnosticFrameAssemblyError
from ashare_lab.research.factors.runtime_source import (
    ArtifactFactorScoreSource,
    FactorRuntimeSourceError,
    VerifiedArtifactFrameReader,
)
from ashare_lab.research.factors.selection import FactorDecisionStatus
from ashare_lab.research.preprocessing.fold import FoldPreprocessingError
from ashare_lab.research.splits.walk_forward import SplitIntegrityError
from ashare_lab.services.factor_calendar_runtime import (
    FactorCalendarRuntimeError,
    load_dataset_development_calendar,
)
from ashare_lab.services.portfolio_research import (
    PortfolioBuildRequest,
    PortfolioResearchError,
    build_portfolio_targets,
)


class PortfolioRuntimeError(Exception):
    """Frozen research evidence cannot publish real portfolio targets."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable portfolio runtime failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"portfolio_runtime: {self.detail}"


def run_default_portfolio_targets(
    project_root: Path,
    factor_report_id: str,
) -> PortfolioTargetDescriptor:
    """Verify one report and publish all label-free development Top 30 targets."""
    artifact_root = project_root / "data" / "artifacts"
    try:
        report_path = artifact_root / "factor_report" / factor_report_id / "report.json"
        report = FactorReportStore(artifact_root).read(
            FactorReportDescriptor(
                report_id=factor_report_id,
                report_path=report_path,
                data_sha256=_sha256(report_path),
            )
        )
        dataset_path = _sole_path(artifact_root / "dataset_spec", "ds_*/manifest.json")
        spec = DatasetSpecStore(artifact_root).read(
            DatasetSpecDescriptor(
                snapshot_id=dataset_path.parent.name,
                manifest_path=dataset_path,
                data_sha256=_sha256(dataset_path),
            )
        )
        trial_path = _sole_path(
            artifact_root / "trial_ledger",
            "trial_batch_*/manifest.json",
        )
        trial_descriptor = TrialBatchDescriptor(
            batch_id=trial_path.parent.name,
            manifest_path=trial_path,
            data_sha256=_sha256(trial_path),
        )
        batch = TrialLedgerStore(artifact_root).read(trial_descriptor)
        if report.dataset_snapshot_id != spec.snapshot_id or report.batch_id != batch.batch_id:
            detail = "factor report crosses DatasetSpec or trial batch boundary"
            raise PortfolioRuntimeError(detail)
        candidates = tuple(
            trial
            for trial, decision in zip(batch.trials, report.decisions, strict=True)
            if decision.status is FactorDecisionStatus.CANDIDATE
        )
        calendar = load_dataset_development_calendar(project_root, spec)
        source = ArtifactFactorScoreSource(
            VerifiedArtifactFrameReader(project_root),
            spec,
            calendar,
        )
        targets = build_portfolio_targets(
            PortfolioBuildRequest(
                factor_report_id,
                spec.snapshot_id,
                batch.batch_id,
                candidates,
            ),
            source,
        )
        return PortfolioTargetStore(artifact_root).write(targets)
    except (
        OSError,
        ValidationError,
        DatasetSpecStoreError,
        TrialLedgerError,
        FactorReportStoreError,
        ResearchArtifactError,
        FactorCalendarRuntimeError,
        FactorRuntimeSourceError,
        DiagnosticFrameAssemblyError,
        FoldPreprocessingError,
        SplitIntegrityError,
        PortfolioConstructionError,
        PortfolioResearchError,
        PortfolioTargetStoreError,
    ) as error:
        raise PortfolioRuntimeError(str(error)) from error


def _sole_path(root: Path, pattern: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one artifact, found {len(paths)}"
        raise PortfolioRuntimeError(detail)
    return paths[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
