"""Sole composition root allowed to open a model final holdout."""

import hashlib
from pathlib import Path

import polars as pl

from ashare_lab.research.experiments.promotion_models import PromotionDecision
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
from ashare_lab.research.splits.final_holdout import (
    FinalHoldoutAccessLedger,
    FinalHoldoutAccessRequest,
    FinalHoldoutError,
    FinalHoldoutGate,
    FinalHoldoutPromotionEvidence,
    FinalHoldoutSpec,
    FrozenResearchProtocol,
)


class ModelFinalHoldoutError(Exception):
    """Promotion or authorization evidence cannot open the final holdout."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable final evaluation blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the governed boundary and concrete blocker."""
        return f"model_final_holdout: {self.detail}"


def open_model_final_holdout(
    project_root: Path,
    frame: pl.DataFrame,
    request: FinalHoldoutAccessRequest,
) -> pl.DataFrame:
    """Open final data once after persisted all-pass development evidence."""
    try:
        return _open_model_final_holdout(project_root, frame, request)
    except (
        ModelProtocolStoreError,
        PromotionEvaluationStoreError,
        FinalHoldoutError,
    ) as error:
        raise ModelFinalHoldoutError(str(error)) from error


def _open_model_final_holdout(
    project_root: Path,
    frame: pl.DataFrame,
    request: FinalHoldoutAccessRequest,
) -> pl.DataFrame:
    root = project_root / "data" / "artifacts"
    protocol_path = root / "model_protocols" / request.model_protocol_id / "manifest.json"
    protocol = ModelProtocolStore(root).read(
        ModelProtocolDescriptor(
            protocol_id=request.model_protocol_id,
            manifest_path=protocol_path,
            data_sha256=_sha256(protocol_path),
        )
    )
    evaluation_path = root / "model_promotions" / request.promotion_evaluation_id / "report.json"
    evaluation = PromotionEvaluationStore(root).read(
        PromotionEvaluationDescriptor(
            evaluation_id=request.promotion_evaluation_id,
            report_path=evaluation_path,
            data_sha256=_sha256(evaluation_path),
        )
    )
    if (
        evaluation.protocol_id != protocol.protocol_id
        or evaluation.model_id != request.model_id
        or evaluation.dataset_snapshot_id != protocol.dataset_snapshot_id
        or request.dataset_snapshot_id != protocol.dataset_snapshot_id
        or evaluation.final_test_runs != 0
        or protocol.final_holdout.maximum_accesses != 1
        or not protocol.final_holdout.requires_all_development_gates
        or not protocol.final_holdout.requires_manual_authorization
    ):
        detail = "model protocol, promotion evaluation, and authorization differ"
        raise ModelFinalHoldoutError(detail)
    if evaluation.decision is not PromotionDecision.ELIGIBLE_FOR_MANUAL_AUTHORIZATION or not all(
        item.passed for item in evaluation.checks
    ):
        detail = "development gates are not all passed"
        raise ModelFinalHoldoutError(detail)
    spec = FinalHoldoutSpec(
        dataset_snapshot_id=protocol.dataset_snapshot_id,
        development_end=protocol.development_end,
        holdout_start=protocol.final_holdout.holdout_start,
        protocol_version="1.0.0",
    )
    if spec.spec_id != protocol.final_holdout.holdout_spec_id:
        detail = "model protocol holdout boundary differs from its content identity"
        raise ModelFinalHoldoutError(detail)
    frozen = FrozenResearchProtocol(
        holdout_spec_id=spec.spec_id,
        dataset_snapshot_id=spec.dataset_snapshot_id,
        split_protocol_id=protocol.split_protocol,
        preprocessing_version=protocol.preprocessing_version,
        code_commit=protocol.code_commit,
        frozen_at=protocol.registered_at,
        frozen_by=protocol.registered_by,
    )
    promotion = FinalHoldoutPromotionEvidence(
        model_protocol_id=protocol.protocol_id,
        promotion_evaluation_id=request.promotion_evaluation_id,
        model_id=evaluation.model_id,
        dataset_snapshot_id=evaluation.dataset_snapshot_id,
        holdout_spec_id=spec.spec_id,
        all_development_gates_passed=True,
        final_test_runs=0,
    )
    ledger = FinalHoldoutAccessLedger(project_root / "data" / "governance")
    return FinalHoldoutGate(spec, frozen, ledger, promotion).open_once(frame, request)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        detail = f"artifact cannot be read: {path}"
        raise ModelFinalHoldoutError(detail) from error
