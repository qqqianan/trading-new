from datetime import date, timedelta

from ashare_lab.research.splits.walk_forward import WalkForwardConfig, build_walk_forward_folds


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
