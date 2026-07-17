import pytest

from ashare_lab.research.model_governance import (
    ModelGovernanceError,
    ModelPurpose,
    ModelTrainingGuard,
    TrainingManifest,
    ValidationScheme,
)


def _valid_manifest() -> TrainingManifest:
    return TrainingManifest(
        purpose=ModelPurpose.INVESTMENT_DECISION,
        validation_scheme=ValidationScheme.PURGED_WALK_FORWARD,
        uses_synthetic_data=False,
        point_in_time_features=True,
        survivorship_safe_universe=True,
        preprocessing_fit_on_train_only=True,
        final_test_runs=1,
        reproducible_snapshot=True,
        complete_schema_documentation=True,
        complete_data_lineage=True,
        selection_trials=20,
        multiple_testing_control=True,
    )


def test_training_guard_rejects_synthetic_data_for_investment_model() -> None:
    # Given: an otherwise valid model trained on synthetic prices.
    manifest = TrainingManifest(
        purpose=ModelPurpose.INVESTMENT_DECISION,
        validation_scheme=ValidationScheme.WALK_FORWARD,
        uses_synthetic_data=True,
        point_in_time_features=True,
        survivorship_safe_universe=True,
        preprocessing_fit_on_train_only=True,
        final_test_runs=1,
        reproducible_snapshot=True,
        complete_schema_documentation=True,
        complete_data_lineage=True,
        selection_trials=1,
        multiple_testing_control=False,
    )

    # When / Then: the model cannot enter an investment decision path.
    with pytest.raises(ModelGovernanceError, match="synthetic data"):
        ModelTrainingGuard().approve(manifest)


def test_training_guard_rejects_reused_final_test_set() -> None:
    # Given: a researcher inspected the final test set more than once.
    valid = _valid_manifest()
    manifest = TrainingManifest(
        purpose=valid.purpose,
        validation_scheme=valid.validation_scheme,
        uses_synthetic_data=valid.uses_synthetic_data,
        point_in_time_features=valid.point_in_time_features,
        survivorship_safe_universe=valid.survivorship_safe_universe,
        preprocessing_fit_on_train_only=valid.preprocessing_fit_on_train_only,
        final_test_runs=2,
        reproducible_snapshot=valid.reproducible_snapshot,
        complete_schema_documentation=valid.complete_schema_documentation,
        complete_data_lineage=valid.complete_data_lineage,
        selection_trials=valid.selection_trials,
        multiple_testing_control=valid.multiple_testing_control,
    )

    # When / Then: the claimed out-of-sample result is rejected.
    with pytest.raises(ModelGovernanceError, match="final test set"):
        ModelTrainingGuard().approve(manifest)


def test_training_guard_approves_reproducible_purged_walk_forward_protocol() -> None:
    # Given: a fully isolated and reproducible training manifest.
    manifest = _valid_manifest()

    # When: the governance gate evaluates it.
    approval = ModelTrainingGuard().approve(manifest)

    # Then: the approval records the governance version and all passed checks.
    assert approval.approved is True
    assert approval.rulebook_version == "1.1.0"
    assert "final_test_single_use" in approval.checks


@pytest.mark.parametrize(
    ("schema_documented", "lineage_complete", "expected_rule"),
    [
        (False, True, "complete_schema_documentation"),
        (True, False, "complete_data_lineage"),
    ],
)
def test_training_guard_rejects_missing_data_contract_evidence(
    *,
    schema_documented: bool,
    lineage_complete: bool,
    expected_rule: str,
) -> None:
    # Given: a training run missing one required data-governance artifact.
    valid = _valid_manifest()
    manifest = TrainingManifest(
        purpose=valid.purpose,
        validation_scheme=valid.validation_scheme,
        uses_synthetic_data=valid.uses_synthetic_data,
        point_in_time_features=valid.point_in_time_features,
        survivorship_safe_universe=valid.survivorship_safe_universe,
        preprocessing_fit_on_train_only=valid.preprocessing_fit_on_train_only,
        final_test_runs=valid.final_test_runs,
        reproducible_snapshot=valid.reproducible_snapshot,
        complete_schema_documentation=schema_documented,
        complete_data_lineage=lineage_complete,
        selection_trials=valid.selection_trials,
        multiple_testing_control=valid.multiple_testing_control,
    )

    # When / Then: training is rejected before model fitting starts.
    with pytest.raises(ModelGovernanceError, match=expected_rule):
        ModelTrainingGuard().approve(manifest)
