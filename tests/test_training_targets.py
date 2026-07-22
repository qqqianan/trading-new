from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from ashare_lab.research.experiments.manifest import LabelTransform
from ashare_lab.research.training.targets import TRAINING_TARGET_COLUMN, attach_training_target


def test_rank_target_uses_average_ties_and_neutral_singleton() -> None:
    # Given: one tied three-name cross-section and one single-name cross-section.
    timezone = ZoneInfo("Asia/Shanghai")
    frame = pl.DataFrame(
        {
            "decision_time": [
                datetime(2024, 1, 2, 18, tzinfo=timezone),
                datetime(2024, 1, 2, 18, tzinfo=timezone),
                datetime(2024, 1, 2, 18, tzinfo=timezone),
                datetime(2024, 1, 3, 18, tzinfo=timezone),
            ],
            "label": (0.1, 0.2, 0.2, -0.4),
        }
    )

    # When: the frozen cross-sectional percentile transform is applied.
    result = attach_training_target(
        frame,
        "label",
        LabelTransform.CROSS_SECTIONAL_PERCENTILE_RANK,
    )

    # Then: ties share average rank and a singleton receives the neutral midpoint.
    assert result[TRAINING_TARGET_COLUMN].to_list() == [0.0, 0.75, 0.75, 0.5]
