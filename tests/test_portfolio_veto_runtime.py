from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.ml.contracts import ModelArtifact
from ashare_lab.ml.trainers.ridge_models import (
    RidgeExperimentArtifact,
    RidgePredictionArtifact,
)
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.portfolio.research_store import PortfolioTargetStore
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.experiments.portfolio_protocol_identity import (
    create_factor_anchor_veto_protocol,
)
from ashare_lab.research.experiments.portfolio_protocol_models import (
    PortfolioExperimentProtocol,
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
from ashare_lab.research.model_attribution.models import ModelPerformanceAttributionReport
from ashare_lab.research.model_diagnostics.models import ModelDiagnosticReport
from ashare_lab.services import portfolio_veto_runtime
from ashare_lab.services.portfolio_protocol_evidence import PortfolioProtocolEvidence
from ashare_lab.services.portfolio_veto_runtime import (
    PortfolioVetoRuntimeError,
    run_factor_anchor_veto_targets,
)
from ashare_lab.services.ridge_portfolio_runtime import CompleteRidgeScoreRequest

from .test_portfolio_protocol import portfolio_protocol_request_fixture


class MemoryScoreSource:
    """One registered label-free factor score source."""

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame

    def load(self, _trial: FactorTrial) -> pl.DataFrame:
        return self._frame


class DummyReader:
    """Typed placeholder replaced before any artifact read occurs."""


@dataclass(frozen=True, slots=True)
class RuntimeAdapters:
    """Typed external adapters used by one composition-root success scenario."""

    protocol: PortfolioExperimentProtocol
    evidence: PortfolioProtocolEvidence
    report: FactorResearchReport
    batch: TrialBatch
    source: MemoryScoreSource
    model_scores: pl.DataFrame

    def read_protocol(self, _root: Path, _protocol_id: str) -> PortfolioExperimentProtocol:
        return self.protocol

    def load_evidence(self, _root: Path, _attribution_id: str) -> PortfolioProtocolEvidence:
        return self.evidence

    def read_report(self, _root: Path, _report_id: str) -> FactorResearchReport:
        return self.report

    def read_batch(self, _root: Path) -> TrialBatch:
        return self.batch

    def reader(self, _root: Path) -> DummyReader:
        return DummyReader()

    def score_source(
        self,
        _reader: DummyReader,
        _dataset: DatasetSpec,
        _calendar: tuple[date, ...],
    ) -> MemoryScoreSource:
        return self.source

    def descriptor(self, _store: RidgeArtifactStore, model_id: str) -> ModelArtifact:
        return ModelArtifact(
            model_id=model_id,
            training_run_id="run",
            dataset_snapshot_id="ds_abc123",
            artifact_uri="model.json",
            artifact_sha256="e" * 64,
        )

    def predictions(
        self,
        _store: RidgeArtifactStore,
        _descriptor: ModelArtifact,
    ) -> RidgePredictionArtifact:
        return RidgePredictionArtifact.model_construct()

    def model_artifact(
        self,
        _store: RidgeArtifactStore,
        _descriptor: ModelArtifact,
    ) -> RidgeExperimentArtifact:
        return self.evidence.model

    def load_calendar(self, _root: Path, _dataset: DatasetSpec) -> tuple[date, ...]:
        return ()

    def prediction_frame(self, _predictions: RidgePredictionArtifact) -> pl.DataFrame:
        return self.model_scores

    def complete_scores(
        self,
        _request: CompleteRidgeScoreRequest,
        _reader: DummyReader,
        _anchor: pl.DataFrame,
    ) -> pl.DataFrame:
        return self.model_scores

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Replace external readers while retaining the real composition and store."""

        def model_descriptor(store: RidgeArtifactStore, model_id: str) -> ModelArtifact:
            return self.descriptor(store, model_id)

        def model_predictions(
            store: RidgeArtifactStore,
            descriptor: ModelArtifact,
        ) -> RidgePredictionArtifact:
            return self.predictions(store, descriptor)

        def stored_model(
            store: RidgeArtifactStore,
            descriptor: ModelArtifact,
        ) -> RidgeExperimentArtifact:
            return self.model_artifact(store, descriptor)

        monkeypatch.setattr(
            "ashare_lab.services.portfolio_veto_runtime._read_protocol",
            self.read_protocol,
        )
        monkeypatch.setattr(
            portfolio_veto_runtime,
            "load_portfolio_protocol_evidence",
            self.load_evidence,
        )
        monkeypatch.setattr(
            "ashare_lab.services.portfolio_veto_runtime._read_factor_report",
            self.read_report,
        )
        monkeypatch.setattr(
            "ashare_lab.services.portfolio_veto_runtime._read_trial_batch",
            self.read_batch,
        )
        monkeypatch.setattr(
            portfolio_veto_runtime,
            "load_dataset_development_calendar",
            self.load_calendar,
        )
        monkeypatch.setattr(portfolio_veto_runtime, "VerifiedArtifactFrameReader", self.reader)
        monkeypatch.setattr(portfolio_veto_runtime, "ArtifactFactorScoreSource", self.score_source)
        monkeypatch.setattr(RidgeArtifactStore, "descriptor", model_descriptor)
        monkeypatch.setattr(RidgeArtifactStore, "read", stored_model)
        monkeypatch.setattr(RidgeArtifactStore, "read_predictions", model_predictions)
        monkeypatch.setattr(
            portfolio_veto_runtime,
            "build_ridge_prediction_score_frame",
            self.prediction_frame,
        )
        monkeypatch.setattr(
            portfolio_veto_runtime,
            "assemble_complete_ridge_portfolio_scores",
            self.complete_scores,
        )


def _runtime_inputs() -> tuple[
    PortfolioExperimentProtocol,
    PortfolioProtocolEvidence,
    FactorResearchReport,
    TrialBatch,
    MemoryScoreSource,
    pl.DataFrame,
]:
    base_request = portfolio_protocol_request_fixture()
    dataset = DatasetSpec.model_construct(
        schema_manifest_id=base_request.schema_manifest_id,
        lineage_manifest_id=base_request.lineage_manifest_id,
        rulebook_version=base_request.rulebook_version,
    )
    protocol = create_factor_anchor_veto_protocol(
        base_request.model_copy(update={"dataset_snapshot_id": dataset.snapshot_id})
    )
    trial = FactorTrial(
        trial_id="factor_trial_" + "a" * 64,
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        feature_name="factor_a",
        feature_version="1.0.0",
        feature_artifact_id="feature_artifact_" + "b" * 64,
        family=FactorFamily.VALUE,
        expected_direction=ExpectedDirection.HIGHER_IS_BETTER,
        simplicity_rank=0,
        diagnostic_version="1.0.0",
    )
    batch = TrialBatch.model_construct(
        batch_id="trial_batch_" + "d" * 64,
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        trials=(trial,),
    )
    decision = FactorDecision(
        trial_id=trial.trial_id,
        feature_name=trial.feature_name,
        status=FactorDecisionStatus.CANDIDATE,
        reasons=(FactorDecisionReason.PASSES_DIAGNOSTIC_GATES,),
        p_value=0.01,
        q_value=0.02,
    )
    report = FactorResearchReport.model_construct(
        batch_id=batch.batch_id,
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        decisions=(decision,),
    )
    attribution = ModelPerformanceAttributionReport.model_construct(
        diagnostic_report_id=protocol.parent_diagnostic_report_id,
        baseline_backtest_id=protocol.baseline_backtest_id,
        model_backtest_id=protocol.model_backtest_id,
    )
    diagnostic = ModelDiagnosticReport.model_construct(factor_report_id="factor_report_" + "c" * 64)
    model = RidgeExperimentArtifact.model_construct(
        model_id=protocol.parent_model_id,
        prediction_artifact_sha256=protocol.prediction_artifact_sha256,
    )
    baseline = PortfolioBacktestReport.model_construct(
        target_artifact_id=protocol.baseline_target_artifact_id,
        cost_rule_version=protocol.cost_rule_version,
        risk_rule_version=protocol.risk_rule_version,
    )
    model_backtest = PortfolioBacktestReport.model_construct(
        target_artifact_id=protocol.model_target_artifact_id
    )
    evidence = PortfolioProtocolEvidence(
        attribution=attribution,
        diagnostic=diagnostic,
        model=model,
        dataset=dataset,
        baseline_backtest=baseline,
        model_backtest=model_backtest,
        baseline_targets=PortfolioTargetBatch.model_construct(candidate_factor_names=("factor_a",)),
        model_targets=PortfolioTargetBatch.model_construct(),
    )
    day = datetime(2024, 1, 5, 18, tzinfo=ZoneInfo("Asia/Shanghai"))
    rows = tuple((day, f"{index:06d}.SZ", float(index)) for index in range(40))
    factor = pl.DataFrame(
        rows,
        schema=("decision_time", "symbol", "factor_value"),
        orient="row",
    )
    model_scores = factor.rename({"factor_value": "model_score"})
    return protocol, evidence, report, batch, MemoryScoreSource(factor), model_scores


def test_veto_runtime_publishes_protocol_bound_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one exact typed protocol chain and external score adapters.
    protocol, evidence, report, batch, source, model_scores = _runtime_inputs()
    RuntimeAdapters(protocol, evidence, report, batch, source, model_scores).install(monkeypatch)

    # When: the formal runtime publishes the target artifact.
    descriptor_result = run_factor_anchor_veto_targets(tmp_path, protocol.protocol_id)

    # Then: stored targets bind the protocol and reused-development classification.
    targets = PortfolioTargetStore(tmp_path / "data" / "artifacts").read(descriptor_result)
    assert targets.portfolio_protocol_id == protocol.protocol_id
    assert targets.evidence_classification == "REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE"


def test_veto_runtime_translates_missing_protocol_to_stable_blocker(tmp_path: Path) -> None:
    # Given: an artifact root without the requested immutable portfolio protocol.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: missing protocol evidence is translated at the composition boundary.
    with pytest.raises(PortfolioVetoRuntimeError, match="portfolio_veto_runtime"):
        run_factor_anchor_veto_targets(
            tmp_path,
            "portfolio_protocol_" + "a" * 64,
        )


def test_veto_runtime_rejects_requested_protocol_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: stored protocol content does not match the identity requested by the caller.
    protocol, evidence, report, batch, source, model_scores = _runtime_inputs()
    RuntimeAdapters(protocol, evidence, report, batch, source, model_scores).install(monkeypatch)

    # When / Then: parent evidence cannot be published under a different protocol ID.
    with pytest.raises(PortfolioVetoRuntimeError, match="identity differs"):
        run_factor_anchor_veto_targets(
            tmp_path,
            "portfolio_protocol_" + "f" * 64,
        )


def test_veto_runtime_rejects_protocol_field_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: protocol content claims a dataset different from its immutable parent chain.
    protocol, evidence, report, batch, source, model_scores = _runtime_inputs()
    mismatched = protocol.model_copy(update={"dataset_snapshot_id": "ds_different"})
    RuntimeAdapters(mismatched, evidence, report, batch, source, model_scores).install(monkeypatch)

    # When / Then: runtime verification fails before loading factor or model scores.
    with pytest.raises(PortfolioVetoRuntimeError, match="fields differ"):
        run_factor_anchor_veto_targets(
            tmp_path,
            mismatched.protocol_id,
        )


def test_veto_runtime_requires_exactly_one_trial_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: no immutable trial ledger exists beneath the artifact root.
    protocol, evidence, report, batch, source, model_scores = _runtime_inputs()
    adapters = RuntimeAdapters(protocol, evidence, report, batch, source, model_scores)
    monkeypatch.setattr(
        "ashare_lab.services.portfolio_veto_runtime._read_protocol",
        adapters.read_protocol,
    )
    monkeypatch.setattr(
        portfolio_veto_runtime,
        "load_portfolio_protocol_evidence",
        adapters.load_evidence,
    )
    monkeypatch.setattr(
        "ashare_lab.services.portfolio_veto_runtime._read_factor_report",
        adapters.read_report,
    )

    # When / Then: runtime refuses to guess which trial batch supplied the factors.
    with pytest.raises(PortfolioVetoRuntimeError, match="exactly one trial batch, found 0"):
        run_factor_anchor_veto_targets(tmp_path, protocol.protocol_id)
