from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.experiments.portfolio_protocol_identity import (
    create_factor_anchor_veto_protocol,
)
from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.experiments.trial_models import TrialBatch
from ashare_lab.research.factors.models import ExpectedDirection, FactorFamily
from ashare_lab.research.factors.selection import (
    FactorDecision,
    FactorDecisionReason,
    FactorDecisionStatus,
    FactorResearchReport,
)
from ashare_lab.services.portfolio_research import PortfolioResearchError
from ashare_lab.services.portfolio_veto_composition import (
    PortfolioVetoCompositionRequest,
    compose_factor_anchor_veto_targets,
)

from .test_portfolio_protocol import portfolio_protocol_request_fixture


class MemoryScoreSource:
    """Label-free in-memory score source for composition behavior."""

    def __init__(self, frames: dict[str, pl.DataFrame]) -> None:
        self._frames = frames

    def load(self, trial: FactorTrial) -> pl.DataFrame:
        return self._frames[trial.feature_name]


def _trial(name: str, identity: str) -> FactorTrial:
    return FactorTrial(
        trial_id="factor_trial_" + identity * 64,
        dataset_snapshot_id="ds_abc123",
        feature_name=name,
        feature_version="1.0.0",
        feature_artifact_id="feature_artifact_" + identity * 64,
        family=FactorFamily.VALUE,
        expected_direction=ExpectedDirection.HIGHER_IS_BETTER,
        simplicity_rank=0,
        diagnostic_version="1.0.0",
    )


def _composition_inputs() -> tuple[
    PortfolioVetoCompositionRequest,
    MemoryScoreSource,
    pl.DataFrame,
]:
    protocol = create_factor_anchor_veto_protocol(portfolio_protocol_request_fixture())
    trials = (_trial("factor_a", "a"), _trial("factor_b", "b"))
    batch = TrialBatch(
        batch_id="trial_batch_" + "d" * 64,
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        rulebook_version="1.0.0",
        code_commit="e" * 40,
        registered_at=datetime(2024, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
        registered_by="research_owner",
        trials=trials,
    )
    decisions = tuple(
        FactorDecision(
            trial_id=trial.trial_id,
            feature_name=trial.feature_name,
            status=FactorDecisionStatus.CANDIDATE,
            reasons=(FactorDecisionReason.PASSES_DIAGNOSTIC_GATES,),
            p_value=0.01,
            q_value=0.02,
        )
        for trial in trials
    )
    report = FactorResearchReport.model_construct(
        batch_id=batch.batch_id,
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        maximum_q=0.1,
        diagnostics=(),
        decisions=decisions,
    )
    day = datetime(2024, 1, 5, 18, tzinfo=ZoneInfo("Asia/Shanghai"))
    rows = tuple((day, f"{index:06d}.SZ", float(index)) for index in range(40))
    frame = pl.DataFrame(
        rows,
        schema=("decision_time", "symbol", "factor_value"),
        orient="row",
    )
    source = MemoryScoreSource({"factor_a": frame, "factor_b": frame})
    model_scores = frame.rename({"factor_value": "model_score"})
    request = PortfolioVetoCompositionRequest(
        protocol=protocol,
        factor_report_id="factor_report_" + "c" * 64,
        report=report,
        trial_batch=batch,
        baseline_candidate_names=("factor_a", "factor_b"),
    )
    return request, source, model_scores


def test_veto_composition_reuses_registered_factor_candidates() -> None:
    # Given: two accepted trials, complete label-free scores, and keyed Ridge predictions.
    request, source, model_scores = _composition_inputs()

    # When: the composition applies existing factor preprocessing before the veto.
    targets = compose_factor_anchor_veto_targets(request, source, model_scores)

    # Then: the protocol-bound result retains both factor names and no order capability.
    assert targets.candidate_factor_names == (
        "factor_a",
        "factor_b",
        "ridge_bottom_quintile_veto",
    )
    assert targets.portfolio_protocol_id == request.protocol.protocol_id
    assert not hasattr(targets.records[0], "orders")


def test_veto_composition_rejects_factor_report_lineage_mismatch() -> None:
    # Given: a report claims a different dataset than the immutable protocol.
    request, source, model_scores = _composition_inputs()
    mismatched = replace(
        request,
        report=request.report.model_copy(update={"dataset_snapshot_id": "ds_different"}),
    )

    # When / Then: score loading stops before incompatible evidence can be combined.
    with pytest.raises(PortfolioResearchError, match="lineage differ"):
        compose_factor_anchor_veto_targets(mismatched, source, model_scores)
