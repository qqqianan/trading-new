import pytest

from ashare_lab.ml.registry import ModelPromotionError, ModelRecord, ModelStatus, promote_model
from ashare_lab.research.model_governance import ApprovalScope, TrainingApproval


def _draft() -> ModelRecord:
    return ModelRecord(
        model_id="ridge_20260720_001",
        dataset_snapshot_id="ds_abc123",
        training_run_id="run_001",
        status=ModelStatus.DRAFT,
    )


def test_development_training_approval_cannot_promote_model() -> None:
    # Given: a DRAFT model and approval scoped only to development fitting.
    approval = TrainingApproval(
        approved=True,
        scope=ApprovalScope.DEVELOPMENT_TRAINING,
        rulebook_version="1.1.0",
        checks=("final_holdout_sealed",),
    )

    # When / Then: fitting approval cannot be repurposed as validation approval.
    with pytest.raises(ModelPromotionError, match="validation approval"):
        promote_model(_draft(), approval)


def test_validation_approval_promotes_without_mutating_draft() -> None:
    # Given: a separate validation-scoped approval after formal final evaluation.
    draft = _draft()
    approval = TrainingApproval(
        approved=True,
        scope=ApprovalScope.VALIDATION_PROMOTION,
        rulebook_version="1.1.0",
        checks=("single_final_evaluation", "ridge_beats_baseline"),
    )

    # When: registry promotion uses the validation-specific evidence.
    promoted = promote_model(draft, approval)

    # Then: the new record is validated while the original remains DRAFT.
    assert promoted.status is ModelStatus.VALIDATED
    assert draft.status is ModelStatus.DRAFT
