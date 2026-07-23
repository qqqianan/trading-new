from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.training import frame as training_frame_module
from ashare_lab.research.training.frame import (
    TrainingFeatureFrame,
    TrainingFrameAssemblyError,
    assemble_development_training_frame,
)


def _time(day: int) -> datetime:
    return datetime(2024, 1, day, 18, tzinfo=ZoneInfo("Asia/Shanghai"))


def _universe() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "decision_time": [_time(5), _time(5), _time(5)],
            "available_at": [_time(5), _time(5), _time(5)],
            "eligible_for_new_risk": [True, True, False],
        }
    )


def _feature(name: str, values: list[float | None]) -> TrainingFeatureFrame:
    return TrainingFeatureFrame(
        name=name,
        version="1.0.0",
        artifact_id=f"feature_{name}",
        frame=pl.DataFrame(
            {
                "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
                "decision_time": [_time(5), _time(5), _time(5)],
                "feature_id": [name, name, name],
                "feature_version": ["1.0.0"] * 3,
                "value": values,
                "available_at": [_time(5), _time(5), _time(5)],
                "quality_status": ["QUALIFIED"] * 3,
            }
        ),
    )


def _label() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "decision_time": [_time(5), _time(5), _time(5)],
            "label_id": ["return_20d"] * 3,
            "label_version": ["1.0.0"] * 3,
            "value": [0.1, None, -0.2],
        }
    )


def test_training_frame_preserves_eligible_rows_with_null_values() -> None:
    # Given: exact-key artifacts with one feature null and one label null.
    features = (
        _feature("vol_20", [0.2, None, 0.4]),
        _feature("log_total_mv", [9.0, 8.0, 7.0]),
    )

    # When: the governed development frame is assembled.
    frame = assemble_development_training_frame(
        _universe(),
        features,
        _label(),
        label_name="return_20d",
        label_version="1.0.0",
    )

    # Then: eligibility is the only sample filter and model columns have stable order.
    assert frame.columns == [
        "decision_time",
        "symbol",
        "vol_20",
        "log_total_mv",
        "return_20d",
    ]
    assert frame.height == 2
    assert frame["vol_20"].null_count() == 1
    assert frame["return_20d"].null_count() == 1


def test_feature_frame_is_assembled_without_label_capability() -> None:
    # Given: an eligible universe and complete PIT feature artifacts.
    features = (
        _feature("vol_20", [0.2, None, 0.4]),
        _feature("log_total_mv", [9.0, 8.0, 7.0]),
    )

    # When: a portfolio scorer requests the governed development feature frame.
    frame = training_frame_module.assemble_development_feature_frame(
        _universe(),
        features,
    )

    # Then: all eligible keys and feature values survive without a label input.
    assert frame.columns == ["decision_time", "symbol", "vol_20", "log_total_mv"]
    assert frame.height == 2
    assert frame["vol_20"].null_count() == 1


def test_training_frame_rejects_duplicate_artifact_keys() -> None:
    # Given: one feature repeats a governed observation key.
    feature = _feature("vol_20", [0.2, 0.3, 0.4])
    duplicate = TrainingFeatureFrame(
        name=feature.name,
        version=feature.version,
        artifact_id=feature.artifact_id,
        frame=pl.concat((feature.frame, feature.frame.head(1))),
    )

    # When / Then: assembly fails instead of multiplying training samples.
    with pytest.raises(TrainingFrameAssemblyError, match="duplicate keys: vol_20"):
        assemble_development_training_frame(
            _universe(),
            (duplicate,),
            _label(),
            label_name="return_20d",
            label_version="1.0.0",
        )


def test_training_frame_rejects_missing_artifact_keys() -> None:
    # Given: a feature artifact omits an eligible universe observation.
    feature = _feature("vol_20", [0.2, 0.3, 0.4])
    incomplete = TrainingFeatureFrame(
        name=feature.name,
        version=feature.version,
        artifact_id=feature.artifact_id,
        frame=feature.frame.head(1),
    )

    # When / Then: a left join cannot silently turn a missing row into an ordinary null value.
    with pytest.raises(TrainingFrameAssemblyError, match="missing universe keys: vol_20"):
        assemble_development_training_frame(
            _universe(),
            (incomplete,),
            _label(),
            label_name="return_20d",
            label_version="1.0.0",
        )


def test_training_frame_rejects_future_available_universe() -> None:
    # Given: eligibility evidence that was not available at decision time.
    universe = _universe().with_columns(pl.col("available_at").dt.offset_by("1d"))

    # When / Then: time-traveling universe rows fail closed.
    with pytest.raises(TrainingFrameAssemblyError, match="future-available rows"):
        assemble_development_training_frame(
            universe,
            (_feature("vol_20", [0.2, 0.3, 0.4]),),
            _label(),
            label_name="return_20d",
            label_version="1.0.0",
        )


def test_training_frame_rejects_future_available_feature() -> None:
    # Given: a feature whose source clock is after the decision.
    feature = _feature("vol_20", [0.2, 0.3, 0.4])
    feature = TrainingFeatureFrame(
        feature.name,
        feature.version,
        feature.artifact_id,
        feature.frame.with_columns(pl.col("available_at").dt.offset_by("1d")),
    )

    # When / Then: the PIT guard rejects the whole feature artifact.
    with pytest.raises(TrainingFrameAssemblyError, match="future-available feature"):
        assemble_development_training_frame(
            _universe(),
            (feature,),
            _label(),
            label_name="return_20d",
            label_version="1.0.0",
        )


def test_training_frame_rejects_wrong_label_identity() -> None:
    # Given: label rows relabeled as a different target definition.
    label = _label().with_columns(pl.lit("other_label").alias("label_id"))

    # When / Then: matching keys cannot hide the semantic identity mismatch.
    with pytest.raises(TrainingFrameAssemblyError, match="artifact identity differs"):
        assemble_development_training_frame(
            _universe(),
            (_feature("vol_20", [0.2, 0.3, 0.4]),),
            label,
            label_name="return_20d",
            label_version="1.0.0",
        )


def test_training_frame_rejects_empty_eligible_universe() -> None:
    # Given: a fail-closed universe with no symbol admitted for new risk.
    universe = _universe().with_columns(pl.lit(value=False).alias("eligible_for_new_risk"))

    # When / Then: training cannot proceed from an empty admitted population.
    with pytest.raises(TrainingFrameAssemblyError, match="eligible development universe is empty"):
        assemble_development_training_frame(
            universe,
            (_feature("vol_20", [0.2, 0.3, 0.4]),),
            _label(),
            label_name="return_20d",
            label_version="1.0.0",
        )
