"""Deterministic training-target transforms that preserve physical labels."""

from typing import Final

import polars as pl

from ashare_lab.research.experiments.manifest import LabelTransform

TRAINING_TARGET_COLUMN: Final = "__training_target"


def attach_training_target(
    frame: pl.DataFrame,
    label_name: str,
    transform: LabelTransform,
) -> pl.DataFrame:
    """Attach the declared fitting target without replacing the raw future return."""
    match transform:
        case LabelTransform.IDENTITY:
            expression = pl.col(label_name)
        case LabelTransform.CROSS_SECTIONAL_PERCENTILE_RANK:
            count = pl.len().over("decision_time")
            rank = pl.col(label_name).rank(method="average").over("decision_time")
            expression = pl.when(count == 1).then(0.5).otherwise((rank - 1.0) / (count - 1))
    return frame.with_columns(expression.cast(pl.Float64).alias(TRAINING_TARGET_COLUMN))
