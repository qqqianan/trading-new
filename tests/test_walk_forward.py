from datetime import date, timedelta

import pytest

from ashare_lab.research.splits.walk_forward import (
    MEDIUM_HORIZON_CONFIG,
    SplitIntegrityError,
    WalkForwardConfig,
    build_development_folds,
    build_walk_forward_folds,
)


def test_walk_forward_folds_keep_purge_and_embargo_gaps() -> None:
    # Given: thirty ordered observation dates and a compact rolling protocol.
    start = date(2020, 1, 1)
    dates = tuple(start + timedelta(days=index) for index in range(30))
    config = WalkForwardConfig(
        minimum_train_size=10,
        validation_size=5,
        test_size=5,
        step_size=5,
        purge_size=2,
        embargo_size=2,
    )

    # When: expanding walk-forward folds are constructed.
    folds = build_walk_forward_folds(dates, config)

    # Then: two folds fit, with explicit unused gaps around evaluation windows.
    assert len(folds) == 2
    assert folds[0].train == dates[0:10]
    assert folds[0].validation == dates[12:17]
    assert folds[0].test == dates[19:24]
    assert folds[1].train == dates[0:15]
    assert folds[1].validation == dates[17:22]
    assert folds[1].test == dates[24:29]


def test_medium_horizon_protocol_uses_frozen_observation_counts() -> None:
    # Given: the constitutionally frozen medium-horizon split protocol.
    # When: its observation counts are inspected.
    counts = (
        MEDIUM_HORIZON_CONFIG.minimum_train_size,
        MEDIUM_HORIZON_CONFIG.validation_size,
        MEDIUM_HORIZON_CONFIG.test_size,
        MEDIUM_HORIZON_CONFIG.step_size,
        MEDIUM_HORIZON_CONFIG.purge_size,
        MEDIUM_HORIZON_CONFIG.embargo_size,
    )

    # Then: development research cannot silently tune the time protocol.
    assert counts == (504, 126, 63, 63, 20, 5)


def test_development_folds_exclude_final_holdout_and_isolate_training_labels() -> None:
    # Given: enough ordered trading dates through the frozen development cutoff.
    start = date(2020, 1, 1)
    dates = tuple(start + timedelta(days=index) for index in range(1500))

    # When: governed development folds are built.
    folds = build_development_folds(dates)

    # Then: the final holdout is absent and a 20-observation label cannot reach validation.
    assert folds
    latest = max(day for fold in folds for day in (*fold.train, *fold.validation, *fold.test))
    assert latest <= date(2024, 12, 31)
    assert all((fold.validation[0] - fold.train[-1]).days > 20 for fold in folds)


def test_development_folds_reject_dates_from_final_holdout() -> None:
    # Given: a caller has mixed one sealed date into the development calendar.
    start = date(2023, 1, 1)
    dates = tuple(start + timedelta(days=index) for index in range(800))

    # When / Then: split construction fails closed instead of filtering silently.
    with pytest.raises(SplitIntegrityError, match="final holdout"):
        build_development_folds(dates)


def test_walk_forward_rejects_nonpositive_training_size() -> None:
    # Given: a split protocol with no initial training observations.
    config = WalkForwardConfig(0, 5, 5, 5, 2, 2)

    # When / Then: the invalid protocol cannot produce folds.
    with pytest.raises(SplitIntegrityError, match="must be positive"):
        build_walk_forward_folds((date(2024, 1, 1),), config)


def test_walk_forward_rejects_duplicate_observation_dates() -> None:
    # Given: an otherwise valid protocol and a duplicated trading date.
    config = WalkForwardConfig(1, 1, 1, 1, 0, 0)
    dates = (date(2024, 1, 1), date(2024, 1, 1))

    # When / Then: time ordering fails closed.
    with pytest.raises(SplitIntegrityError, match="strictly increasing"):
        build_walk_forward_folds(dates, config)
