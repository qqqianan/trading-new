"""Lossless assembly of governed feature and label artifacts for training."""

from dataclasses import dataclass

import polars as pl

from ashare_lab.research.splits.walk_forward import DEVELOPMENT_END

_KEYS = ("decision_time", "symbol")


@dataclass(frozen=True, slots=True)
class TrainingFeatureFrame:
    """One DatasetSpec-bound feature identity and its verified artifact rows."""

    name: str
    version: str
    artifact_id: str
    frame: pl.DataFrame


@dataclass(frozen=True, slots=True)
class TrainingFrameAssemblyError(Exception):
    """Governed artifacts cannot form one lossless keyed training frame."""

    detail: str

    def __str__(self) -> str:
        """Return the assembly boundary and concrete blocker."""
        return f"training_frame: {self.detail}"


def assemble_development_training_frame(
    universe: pl.DataFrame,
    features: tuple[TrainingFeatureFrame, ...],
    label: pl.DataFrame,
    *,
    label_name: str,
    label_version: str,
) -> pl.DataFrame:
    """Join exact artifact keys without dropping rows or imputing model values."""
    if not features or len(features) != len({item.name for item in features}):
        detail = "feature identities must be non-empty and unique"
        raise TrainingFrameAssemblyError(detail)
    _require_columns(
        universe,
        (*_KEYS, "available_at", "eligible_for_new_risk"),
        "universe",
    )
    _reject_duplicate_keys(universe, "universe")
    if universe.filter(pl.col("available_at") > pl.col("decision_time")).height:
        detail = "universe contains future-available rows"
        raise TrainingFrameAssemblyError(detail)
    result = (
        universe.filter(
            pl.col("eligible_for_new_risk")
            & (pl.col("decision_time").dt.date() <= pl.lit(DEVELOPMENT_END))
        )
        .select(*_KEYS)
        .sort(*_KEYS)
    )
    if result.is_empty():
        detail = "eligible development universe is empty"
        raise TrainingFrameAssemblyError(detail)
    for feature in features:
        result = _join_feature(result, feature)
    result = _join_label(result, label, label_name, label_version)
    return result.select(*_KEYS, *(item.name for item in features), label_name).sort(*_KEYS)


def _join_feature(base: pl.DataFrame, feature: TrainingFeatureFrame) -> pl.DataFrame:
    required = (
        *_KEYS,
        "feature_id",
        "feature_version",
        "value",
        "available_at",
        "quality_status",
    )
    _require_columns(feature.frame, required, feature.name)
    _reject_duplicate_keys(feature.frame, feature.name)
    invalid_identity = feature.frame.filter(
        (pl.col("feature_id") != feature.name) | (pl.col("feature_version") != feature.version)
    )
    if invalid_identity.height:
        detail = f"artifact identity differs: {feature.name}"
        raise TrainingFrameAssemblyError(detail)
    if feature.frame.filter(pl.col("available_at") > pl.col("decision_time")).height:
        detail = f"future-available feature rows: {feature.name}"
        raise TrainingFrameAssemblyError(detail)
    marker = f"__present_{feature.name}"
    values = feature.frame.select(
        *_KEYS,
        pl.col("value").alias(feature.name),
        pl.lit(1, dtype=pl.UInt8).alias(marker),
    )
    joined = base.join(values, on=_KEYS, how="left")
    if joined[marker].null_count():
        detail = f"missing universe keys: {feature.name}"
        raise TrainingFrameAssemblyError(detail)
    return joined.drop(marker)


def _join_label(
    base: pl.DataFrame,
    label: pl.DataFrame,
    label_name: str,
    label_version: str,
) -> pl.DataFrame:
    _require_columns(label, (*_KEYS, "label_id", "label_version", "value"), label_name)
    _reject_duplicate_keys(label, label_name)
    invalid_identity = label.filter(
        (pl.col("label_id") != label_name) | (pl.col("label_version") != label_version)
    )
    if invalid_identity.height:
        detail = f"artifact identity differs: {label_name}"
        raise TrainingFrameAssemblyError(detail)
    marker = "__present_label"
    values = label.select(
        *_KEYS,
        pl.col("value").alias(label_name),
        pl.lit(1, dtype=pl.UInt8).alias(marker),
    )
    joined = base.join(values, on=_KEYS, how="left")
    if joined[marker].null_count():
        detail = f"missing universe keys: {label_name}"
        raise TrainingFrameAssemblyError(detail)
    return joined.drop(marker)


def _reject_duplicate_keys(frame: pl.DataFrame, name: str) -> None:
    if frame.select(*_KEYS).is_duplicated().any():
        detail = f"duplicate keys: {name}"
        raise TrainingFrameAssemblyError(detail)


def _require_columns(frame: pl.DataFrame, required: tuple[str, ...], name: str) -> None:
    missing = set(required).difference(frame.columns)
    if missing:
        detail = f"incomplete columns for {name}: {sorted(missing)}"
        raise TrainingFrameAssemblyError(detail)
