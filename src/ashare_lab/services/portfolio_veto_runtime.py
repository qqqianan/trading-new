"""Composition root for protocol-bound factor-anchor Ridge-veto targets."""

import hashlib
from pathlib import Path

from pydantic import ValidationError

from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.portfolio.research_store import (
    PortfolioTargetDescriptor,
    PortfolioTargetStore,
    PortfolioTargetStoreError,
)
from ashare_lab.research.artifacts.models import ResearchArtifactError
from ashare_lab.research.experiments.portfolio_protocol_models import (
    PortfolioExperimentProtocol,
)
from ashare_lab.research.experiments.portfolio_protocol_store import (
    PortfolioProtocolDescriptor,
    PortfolioProtocolStore,
    PortfolioProtocolStoreError,
)
from ashare_lab.research.experiments.trial_ledger import TrialLedgerError, TrialLedgerStore
from ashare_lab.research.experiments.trial_models import TrialBatch, TrialBatchDescriptor
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
from ashare_lab.research.factors.selection import FactorResearchReport
from ashare_lab.research.preprocessing.fold import FoldPreprocessingError
from ashare_lab.research.preprocessing.store import FoldPreprocessorStoreError
from ashare_lab.research.splits.walk_forward import SplitIntegrityError, build_development_folds
from ashare_lab.research.training.frame import TrainingFrameAssemblyError
from ashare_lab.services.factor_calendar_runtime import (
    FactorCalendarRuntimeError,
    load_dataset_development_calendar,
)
from ashare_lab.services.model_prediction import (
    RidgePredictionFrameError,
    build_ridge_prediction_score_frame,
)
from ashare_lab.services.portfolio_protocol_evidence import (
    PortfolioProtocolEvidence,
    PortfolioProtocolEvidenceError,
    load_portfolio_protocol_evidence,
)
from ashare_lab.services.portfolio_research import PortfolioResearchError
from ashare_lab.services.portfolio_veto_composition import (
    PortfolioVetoCompositionRequest,
    compose_factor_anchor_veto_targets,
)
from ashare_lab.services.portfolio_veto_research import PortfolioVetoResearchError
from ashare_lab.services.ridge_portfolio_runtime import (
    CompleteRidgeScoreRequest,
    assemble_complete_ridge_portfolio_scores,
)


class PortfolioVetoRuntimeError(Exception):
    """A protocol and its frozen sources cannot form candidate targets."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable runtime blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"portfolio_veto_runtime: {self.detail}"


def run_factor_anchor_veto_targets(
    project_root: Path,
    protocol_id: str,
) -> PortfolioTargetDescriptor:
    """Build reused-development targets without labels, orders, or holdout access."""
    try:
        return _run_factor_anchor_veto_targets(project_root, protocol_id)
    except (
        OSError,
        ValidationError,
        PortfolioProtocolStoreError,
        PortfolioProtocolEvidenceError,
        RidgeArtifactStoreError,
        TrialLedgerError,
        FactorReportStoreError,
        ResearchArtifactError,
        FactorCalendarRuntimeError,
        FactorRuntimeSourceError,
        DiagnosticFrameAssemblyError,
        FoldPreprocessingError,
        FoldPreprocessorStoreError,
        SplitIntegrityError,
        TrainingFrameAssemblyError,
        RidgePredictionFrameError,
        PortfolioResearchError,
        PortfolioVetoResearchError,
        PortfolioTargetStoreError,
    ) as error:
        raise PortfolioVetoRuntimeError(str(error)) from error


def _run_factor_anchor_veto_targets(
    project_root: Path,
    protocol_id: str,
) -> PortfolioTargetDescriptor:
    root = project_root / "data" / "artifacts"
    protocol = _read_protocol(root, protocol_id)
    evidence = load_portfolio_protocol_evidence(
        root,
        protocol.parent_attribution_report_id,
    )
    _verify_protocol(protocol_id, protocol, evidence)
    report = _read_factor_report(root, evidence.diagnostic.factor_report_id)
    batch = _read_trial_batch(root)
    calendar = load_dataset_development_calendar(project_root, evidence.dataset)
    source = ArtifactFactorScoreSource(
        VerifiedArtifactFrameReader(project_root),
        evidence.dataset,
        calendar,
    )
    model_store = RidgeArtifactStore(root)
    model_descriptor = model_store.descriptor(protocol.parent_model_id)
    model = model_store.read(model_descriptor)
    anchor_scores = build_ridge_prediction_score_frame(
        model_store.read_predictions(model_descriptor)
    )
    model_scores = assemble_complete_ridge_portfolio_scores(
        CompleteRidgeScoreRequest(
            artifact_root=root,
            spec=evidence.dataset,
            model=model,
            folds=build_development_folds(calendar),
        ),
        VerifiedArtifactFrameReader(project_root),
        anchor_scores,
    )
    targets = compose_factor_anchor_veto_targets(
        PortfolioVetoCompositionRequest(
            protocol=protocol,
            factor_report_id=evidence.diagnostic.factor_report_id,
            report=report,
            trial_batch=batch,
            baseline_candidate_names=evidence.baseline_targets.candidate_factor_names,
        ),
        source,
        model_scores,
    )
    return PortfolioTargetStore(root).write(targets)


def _verify_protocol(
    protocol_id: str,
    protocol: PortfolioExperimentProtocol,
    evidence: PortfolioProtocolEvidence,
) -> None:
    if protocol.protocol_id != protocol_id:
        detail = "portfolio protocol identity differs from parent evidence"
        raise PortfolioVetoRuntimeError(detail)
    if (
        protocol.dataset_snapshot_id != evidence.dataset.snapshot_id
        or protocol.schema_manifest_id != evidence.dataset.schema_manifest_id
        or protocol.lineage_manifest_id != evidence.dataset.lineage_manifest_id
        or protocol.rulebook_version != evidence.dataset.rulebook_version
        or protocol.parent_diagnostic_report_id != evidence.attribution.diagnostic_report_id
        or protocol.parent_model_id != evidence.model.model_id
        or protocol.prediction_artifact_sha256 != evidence.model.prediction_artifact_sha256
        or protocol.baseline_target_artifact_id != evidence.baseline_backtest.target_artifact_id
        or protocol.baseline_backtest_id != evidence.attribution.baseline_backtest_id
        or protocol.model_target_artifact_id != evidence.model_backtest.target_artifact_id
        or protocol.model_backtest_id != evidence.attribution.model_backtest_id
        or protocol.cost_rule_version != evidence.baseline_backtest.cost_rule_version
        or protocol.risk_rule_version != evidence.baseline_backtest.risk_rule_version
        or protocol.status != "PREREGISTERED_NOT_IMPLEMENTED"
        or protocol.fresh_forward.final_holdout_access_permitted
    ):
        detail = "portfolio protocol fields differ from parent evidence"
        raise PortfolioVetoRuntimeError(detail)


def _read_protocol(root: Path, protocol_id: str) -> PortfolioExperimentProtocol:
    path = root / "portfolio_protocols" / protocol_id / "manifest.json"
    return PortfolioProtocolStore(root).read(
        PortfolioProtocolDescriptor(
            protocol_id=protocol_id,
            manifest_path=path,
            data_sha256=_sha256(path),
        )
    )


def _read_factor_report(root: Path, report_id: str) -> FactorResearchReport:
    path = root / "factor_report" / report_id / "report.json"
    return FactorReportStore(root).read(
        FactorReportDescriptor(
            report_id=report_id,
            report_path=path,
            data_sha256=_sha256(path),
        )
    )


def _read_trial_batch(root: Path) -> TrialBatch:
    paths = tuple((root / "trial_ledger").glob("trial_batch_*/manifest.json"))
    if len(paths) != 1:
        detail = f"expected exactly one trial batch, found {len(paths)}"
        raise PortfolioVetoRuntimeError(detail)
    path = paths[0]
    return TrialLedgerStore(root).read(
        TrialBatchDescriptor(
            batch_id=path.parent.name,
            manifest_path=path,
            data_sha256=_sha256(path),
        )
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
