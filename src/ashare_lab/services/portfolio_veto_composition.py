"""Pure composition from governed factor trials and model scores to veto targets."""

from dataclasses import dataclass

import polars as pl

from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.research.experiments.portfolio_protocol_models import (
    PortfolioExperimentProtocol,
)
from ashare_lab.research.experiments.trial_models import TrialBatch
from ashare_lab.research.factors.selection import FactorDecisionStatus, FactorResearchReport
from ashare_lab.services.portfolio_research import (
    PortfolioBuildRequest,
    PortfolioResearchError,
    PortfolioScoreFrameSource,
    build_factor_composite_scores,
)
from ashare_lab.services.portfolio_veto_research import (
    FactorAnchorVetoBuildRequest,
    build_factor_anchor_veto_targets,
)


@dataclass(frozen=True, slots=True)
class PortfolioVetoCompositionRequest:
    """Exact research identities admitted to label-free score composition."""

    protocol: PortfolioExperimentProtocol
    factor_report_id: str
    report: FactorResearchReport
    trial_batch: TrialBatch
    baseline_candidate_names: tuple[str, ...]


def compose_factor_anchor_veto_targets(
    request: PortfolioVetoCompositionRequest,
    source: PortfolioScoreFrameSource,
    model_scores: pl.DataFrame,
) -> PortfolioTargetBatch:
    """Reuse governed factor preprocessing before applying the protocol veto."""
    protocol = request.protocol
    report = request.report
    batch = request.trial_batch
    candidates = tuple(
        trial
        for trial, decision in zip(batch.trials, report.decisions, strict=True)
        if decision.status is FactorDecisionStatus.CANDIDATE
    )
    names = tuple(item.feature_name for item in candidates)
    if (
        report.dataset_snapshot_id != protocol.dataset_snapshot_id
        or batch.dataset_snapshot_id != protocol.dataset_snapshot_id
        or report.batch_id != batch.batch_id
        or names != request.baseline_candidate_names
    ):
        detail = "factor report, trial batch, and baseline target lineage differ"
        raise PortfolioResearchError(detail)
    composite = build_factor_composite_scores(
        PortfolioBuildRequest(
            factor_report_id=request.factor_report_id,
            dataset_snapshot_id=protocol.dataset_snapshot_id,
            trial_batch_id=batch.batch_id,
            candidate_trials=candidates,
        ),
        source,
    )
    return build_factor_anchor_veto_targets(
        FactorAnchorVetoBuildRequest(
            protocol=protocol,
            factor_report_id=request.factor_report_id,
            trial_batch_id=batch.batch_id,
            candidate_factor_names=composite.candidate_factor_names,
        ),
        composite.frame,
        model_scores,
    )
