"""Composition root for protocol-bound development promotion evaluation."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore, RidgeArtifactStoreError
from ashare_lab.research.experiments.manifest import LabelTransform, ModelFamily
from ashare_lab.research.experiments.promotion import evaluate_model_promotion
from ashare_lab.research.experiments.promotion_models import ModelPromotionEvaluation
from ashare_lab.research.experiments.promotion_store import (
    PromotionEvaluationDescriptor,
    PromotionEvaluationStore,
    PromotionEvaluationStoreError,
)
from ashare_lab.research.experiments.protocol_store import (
    ModelProtocolDescriptor,
    ModelProtocolStore,
    ModelProtocolStoreError,
)
from ashare_lab.research.model_diagnostics.store import (
    ModelDiagnosticDescriptor,
    ModelDiagnosticStore,
    ModelDiagnosticStoreError,
)
from ashare_lab.research.splits.final_holdout import (
    FinalHoldoutAccessLedger,
    FinalHoldoutError,
)


class ModelPromotionRuntimeError(Exception):
    """Frozen model evidence cannot form one promotion evaluation."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable runtime blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"model_promotion_runtime: {self.detail}"


@dataclass(frozen=True, slots=True)
class ModelPromotionRuntimeResult:
    """Persisted identity plus the exact development-only decision."""

    descriptor: PromotionEvaluationDescriptor
    evaluation: ModelPromotionEvaluation


def run_default_model_promotion_evaluation(
    project_root: Path,
    protocol_id: str,
    model_id: str,
    diagnostic_report_id: str,
) -> ModelPromotionRuntimeResult:
    """Verify exact lineage and publish all preregistered gate outcomes."""
    try:
        return _run_default_model_promotion_evaluation(
            project_root,
            protocol_id,
            model_id,
            diagnostic_report_id,
        )
    except (
        ModelProtocolStoreError,
        RidgeArtifactStoreError,
        ModelDiagnosticStoreError,
        PromotionEvaluationStoreError,
        FinalHoldoutError,
    ) as error:
        raise ModelPromotionRuntimeError(str(error)) from error


def _run_default_model_promotion_evaluation(
    project_root: Path,
    protocol_id: str,
    model_id: str,
    diagnostic_report_id: str,
) -> ModelPromotionRuntimeResult:
    root = project_root / "data" / "artifacts"
    protocol_path = root / "model_protocols" / protocol_id / "manifest.json"
    protocol = ModelProtocolStore(root).read(
        ModelProtocolDescriptor(
            protocol_id=protocol_id,
            manifest_path=protocol_path,
            data_sha256=_sha256(protocol_path),
        )
    )
    model_store = RidgeArtifactStore(root)
    model = model_store.read(model_store.descriptor(model_id))
    diagnostic_path = root / "model_diagnostics" / diagnostic_report_id / "report.json"
    diagnostic = ModelDiagnosticStore(root).read(
        ModelDiagnosticDescriptor(
            report_id=diagnostic_report_id,
            report_path=diagnostic_path,
            data_sha256=_sha256(diagnostic_path),
        )
    )
    if (
        model.model_id != model_id
        or model.experiment_protocol_id != protocol.protocol_id
        or diagnostic.model_id != model.model_id
        or diagnostic.dataset_snapshot_id != protocol.dataset_snapshot_id
        or model.dataset_snapshot_id != protocol.dataset_snapshot_id
        or model.schema_manifest_id != protocol.schema_manifest_id
        or model.lineage_manifest_id != protocol.lineage_manifest_id
        or model.training_feature_names != protocol.feature_names
        or model.prediction_artifact_sha256 != diagnostic.prediction_artifact_sha256
        or model.factor_report_id != diagnostic.factor_report_id
        or model.selected_alpha != diagnostic.selected_alpha
        or model.cost_rule_version != protocol.cost_rule_version
        or model.model_family is not ModelFamily.RIDGE_RANK
        or model.label_transform is not LabelTransform.CROSS_SECTIONAL_PERCENTILE_RANK
    ):
        detail = "protocol, model, and diagnostic lineage differ"
        raise ModelPromotionRuntimeError(detail)
    if (
        model.model_status != "DRAFT"
        or model.final_test_runs != 0
        or diagnostic.model_status != "DRAFT"
        or diagnostic.final_test_runs != 0
        or diagnostic.diagnostic_scope != "POST_HOC_DEVELOPMENT_ONLY"
        or diagnostic.tuning_permitted
    ):
        detail = "promotion evaluation requires sealed development-only DRAFT evidence"
        raise ModelPromotionRuntimeError(detail)
    holdout_count = FinalHoldoutAccessLedger(project_root / "data" / "governance").count(
        protocol.final_holdout.holdout_spec_id
    )
    if holdout_count != 0:
        detail = "final holdout was already opened"
        raise ModelPromotionRuntimeError(detail)
    evaluation = evaluate_model_promotion(protocol, diagnostic_report_id, diagnostic)
    descriptor = PromotionEvaluationStore(root).write(evaluation)
    return ModelPromotionRuntimeResult(descriptor, evaluation)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise ModelPromotionRuntimeError(detail) from error
