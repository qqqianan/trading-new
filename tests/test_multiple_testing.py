import pytest

from ashare_lab.research.factors.multiple_testing import (
    MultipleTestingError,
    PValueObservation,
    benjamini_hochberg,
)


def test_bh_fdr_adjusts_in_original_trial_order() -> None:
    # Given: three registered trials in a non-sorted p-value order.
    observations = (
        PValueObservation(trial_id="trial_b", p_value=0.04),
        PValueObservation(trial_id="trial_a", p_value=0.01),
        PValueObservation(trial_id="trial_c", p_value=0.50),
    )

    # When: BH-FDR is applied at q <= 10%.
    results = benjamini_hochberg(observations, maximum_q=0.10)

    # Then: identities retain ledger order and adjusted q-values are monotone-corrected.
    assert tuple(item.trial_id for item in results) == ("trial_b", "trial_a", "trial_c")
    assert tuple(round(item.q_value, 3) for item in results) == (0.06, 0.03, 0.5)
    assert tuple(item.significant for item in results) == (True, True, False)


def test_adding_noise_trials_changes_fdr_decision() -> None:
    # Given: two initially significant trials and eight additional registered noise trials.
    original = (
        PValueObservation(trial_id="signal_a", p_value=0.01),
        PValueObservation(trial_id="signal_b", p_value=0.04),
    )
    noise = tuple(PValueObservation(trial_id=f"noise_{index}", p_value=1.0) for index in range(8))

    # When: the same signal is corrected before and after all attempts are disclosed.
    before = benjamini_hochberg(original, maximum_q=0.05)
    after = benjamini_hochberg((*original, *noise), maximum_q=0.05)

    # Then: hidden trial count cannot leave the selection result unchanged.
    assert tuple(item.significant for item in before) == (True, True)
    assert tuple(item.significant for item in after[:2]) == (False, False)


def test_bh_fdr_rejects_invalid_q_threshold() -> None:
    # Given: one disclosed p-value and an impossible FDR threshold.
    observations = (PValueObservation(trial_id="trial", p_value=0.5),)

    # When / Then: correction fails instead of silently clamping governance config.
    with pytest.raises(MultipleTestingError, match="maximum_q"):
        benjamini_hochberg(observations, maximum_q=0.0)


def test_bh_fdr_accepts_empty_disclosed_batch_as_empty_result() -> None:
    # Given: no registered p-value observations.
    # When: correction is requested for the empty tuple.
    results = benjamini_hochberg((), maximum_q=0.10)

    # Then: it returns no invented trial result.
    assert results == ()
