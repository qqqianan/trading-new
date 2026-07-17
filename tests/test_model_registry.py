from ashare_lab.ml.registry import ModelRecord, ModelStatus, promote_model
from ashare_lab.research.model_governance import TrainingApproval


def test_model_promotion_requires_governance_approval() -> None:
    # Given: a draft model and versioned governance approval.
    draft = ModelRecord(
        model_id="lgbm_ranker_20260714_001",
        dataset_snapshot_id="ds_abc123",
        training_run_id="run_001",
        status=ModelStatus.DRAFT,
    )
    approval = TrainingApproval(
        approved=True,
        rulebook_version="1.1.0",
        checks=("point_in_time_features", "final_test_single_use"),
    )

    # When: the model is promoted through the registry contract.
    promoted = promote_model(draft, approval)

    # Then: a new immutable validated record retains its lineage.
    assert promoted.status is ModelStatus.VALIDATED
    assert promoted.model_id == draft.model_id
    assert promoted.dataset_snapshot_id == draft.dataset_snapshot_id
    assert draft.status is ModelStatus.DRAFT
