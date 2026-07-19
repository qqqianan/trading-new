"""Expanding walk-forward splits with purge and embargo gaps."""

from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Final


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    """Observation counts controlling an expanding time split."""

    minimum_train_size: int
    validation_size: int
    test_size: int
    step_size: int
    purge_size: int
    embargo_size: int


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """Ordered observations used by one training and evaluation fold."""

    fold_index: int
    train: tuple[date, ...]
    validation: tuple[date, ...]
    test: tuple[date, ...]


DEVELOPMENT_END: Final = date(2024, 12, 31)
LABEL_HORIZON: Final = 20
MEDIUM_HORIZON_CONFIG: Final = WalkForwardConfig(
    minimum_train_size=504,
    validation_size=126,
    test_size=63,
    step_size=63,
    purge_size=20,
    embargo_size=5,
)


class SplitIntegrityError(Exception):
    """Input dates or split sizes cannot form a valid time protocol."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed split failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the concrete split-integrity failure."""
        return self.detail


def build_walk_forward_folds(
    dates: tuple[date, ...],
    config: WalkForwardConfig,
) -> tuple[WalkForwardFold, ...]:
    """Build expanding folds while leaving purge and embargo observations unused."""
    _validate_inputs(dates, config)
    folds: list[WalkForwardFold] = []
    train_end = config.minimum_train_size
    while True:
        validation_start = train_end + config.purge_size
        validation_end = validation_start + config.validation_size
        test_start = validation_end + config.embargo_size
        test_end = test_start + config.test_size
        if test_end > len(dates):
            break
        folds.append(
            WalkForwardFold(
                fold_index=len(folds),
                train=dates[:train_end],
                validation=dates[validation_start:validation_end],
                test=dates[test_start:test_end],
            )
        )
        train_end += config.step_size
    return tuple(folds)


def build_development_folds(dates: tuple[date, ...]) -> tuple[WalkForwardFold, ...]:
    """Build the frozen protocol only from physically isolated development dates."""
    if dates and dates[-1] > DEVELOPMENT_END:
        detail = "development calendar contains a date from the final holdout"
        raise SplitIntegrityError(detail)
    folds = build_walk_forward_folds(dates, MEDIUM_HORIZON_CONFIG)
    for fold in folds:
        if dates.index(fold.validation[0]) - dates.index(fold.train[-1]) <= LABEL_HORIZON:
            detail = "training label window overlaps validation"
            raise SplitIntegrityError(detail)
    return folds


def _validate_inputs(dates: tuple[date, ...], config: WalkForwardConfig) -> None:
    sizes = (
        config.minimum_train_size,
        config.validation_size,
        config.test_size,
        config.step_size,
    )
    if any(size <= 0 for size in sizes):
        detail = "train, validation, test, and step sizes must be positive"
        raise SplitIntegrityError(detail)
    if config.purge_size < 0 or config.embargo_size < 0:
        detail = "purge and embargo sizes cannot be negative"
        raise SplitIntegrityError(detail)
    if any(current <= previous for previous, current in pairwise(dates)):
        detail = "observation dates must be strictly increasing and unique"
        raise SplitIntegrityError(detail)
