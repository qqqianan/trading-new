from pathlib import Path

import pytest

from ashare_lab.ml.contracts import ModelArtifact
from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.research.experiments.manifest import LabelTransform, ModelFamily
from ashare_lab.research.experiments.promotion_models import PromotionDecision
from ashare_lab.research.experiments.promotion_store import PromotionEvaluationStore
from ashare_lab.research.experiments.protocol_identity import create_rank_aligned_protocol
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol
from ashare_lab.research.experiments.protocol_store import (
    ModelProtocolDescriptor,
    ModelProtocolStore,
)
from ashare_lab.research.model_diagnostics.models import ModelDiagnosticReport
from ashare_lab.research.model_diagnostics.store import (
    ModelDiagnosticDescriptor,
    ModelDiagnosticStore,
)
from ashare_lab.services.model_promotion_runtime import run_default_model_promotion_evaluation

from .test_model_promotion import DIAGNOSTIC_ID, passing_diagnostic
from .test_model_protocol import protocol_request


def test_model_promotion_runtime_verifies_exact_chain_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one exact protocol -> rank model -> development diagnostic chain where
    # DatasetSpec input schema and materialized training schema remain distinct.
    artifact_root = tmp_path / "data" / "artifacts"
    protocol = create_rank_aligned_protocol(protocol_request())
    diagnostic = passing_diagnostic()
    model = RidgeExperimentArtifact.model_construct(
        model_id=diagnostic.model_id,
        training_run_id="ridge_run_test",
        dataset_snapshot_id=diagnostic.dataset_snapshot_id,
        schema_manifest_id="schema_" + "9" * 64,
        lineage_manifest_id=protocol.lineage_manifest_id,
        prediction_artifact_sha256=diagnostic.prediction_artifact_sha256,
        factor_report_id=diagnostic.factor_report_id,
        selected_alpha=diagnostic.selected_alpha,
        training_feature_names=protocol.feature_names,
        model_family=ModelFamily.RIDGE_RANK,
        label_transform=LabelTransform.CROSS_SECTIONAL_PERCENTILE_RANK,
        experiment_protocol_id=protocol.protocol_id,
        portfolio_rule_version="1.0.0",
        cost_rule_version=protocol.cost_rule_version,
        model_status="DRAFT",
        final_test_runs=0,
    )
    protocol_path = artifact_root / "model_protocols" / protocol.protocol_id / "manifest.json"
    diagnostic_path = artifact_root / "model_diagnostics" / DIAGNOSTIC_ID / "report.json"
    protocol_path.parent.mkdir(parents=True)
    diagnostic_path.parent.mkdir(parents=True)
    protocol_path.write_text("{}\n", encoding="utf-8")
    diagnostic_path.write_text("{}\n", encoding="utf-8")

    def read_protocol(
        _store: ModelProtocolStore,
        _descriptor: ModelProtocolDescriptor,
    ) -> ModelExperimentProtocol:
        return protocol

    def read_diagnostic(
        _store: ModelDiagnosticStore,
        _descriptor: ModelDiagnosticDescriptor,
    ) -> ModelDiagnosticReport:
        return diagnostic

    def model_descriptor(_store: RidgeArtifactStore, _model_id: str) -> ModelArtifact:
        return ModelArtifact(
            model.model_id,
            model.training_run_id,
            model.dataset_snapshot_id,
            "manifest.json",
            "a" * 64,
        )

    def read_model(
        _store: RidgeArtifactStore,
        _descriptor: ModelArtifact,
    ) -> RidgeExperimentArtifact:
        return model

    monkeypatch.setattr(ModelProtocolStore, "read", read_protocol)
    monkeypatch.setattr(ModelDiagnosticStore, "read", read_diagnostic)
    monkeypatch.setattr(RidgeArtifactStore, "descriptor", model_descriptor)
    monkeypatch.setattr(RidgeArtifactStore, "read", read_model)

    # When: the formal composition root evaluates the frozen development gates.
    result = run_default_model_promotion_evaluation(
        tmp_path,
        protocol.protocol_id,
        model.model_id,
        DIAGNOSTIC_ID,
    )

    # Then: the content-addressed decision is published without holdout authority.
    stored = PromotionEvaluationStore(artifact_root).read(result.descriptor)
    assert stored == result.evaluation
    assert stored.decision is PromotionDecision.ELIGIBLE_FOR_MANUAL_AUTHORIZATION
    assert stored.final_holdout_authorized is False
