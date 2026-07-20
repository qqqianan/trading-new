"""Fold-local assembly of out-of-sample factor diagnostic frames."""

from dataclasses import dataclass

import polars as pl

from ashare_lab.research.preprocessing import FoldPreprocessor
from ashare_lab.research.splits.walk_forward import WalkForwardFold

_KEYS = ("decision_time", "symbol")
_SIZE_FEATURE = "log_total_mv"


@dataclass(frozen=True, slots=True)
class DiagnosticFrameAssemblyError(Exception):
    """Artifact rows cannot form unique development-test observations."""

    detail: str

    def __str__(self) -> str:
        """Return the assembly boundary and stable detail."""
        return f"diagnostic_frame: {self.detail}"


@dataclass(frozen=True, slots=True)
class DiagnosticFrameInputs:
    """Verified universe, feature, size, and label artifact rows."""

    universe: pl.DataFrame
    feature: pl.DataFrame
    size: pl.DataFrame
    label: pl.DataFrame


@dataclass(frozen=True, slots=True)
class ScoreFrameInputs:
    """Verified universe, feature, and size rows without label capability."""

    universe: pl.DataFrame
    feature: pl.DataFrame
    size: pl.DataFrame


def build_oos_score_frame(
    inputs: ScoreFrameInputs,
    folds: tuple[WalkForwardFold, ...],
    *,
    feature_name: str,
    dataset_snapshot_id: str,
) -> pl.DataFrame:
    """Fit per-fold preprocessing and emit label-free internal-test scores."""
    if not folds:
        detail = "walk-forward protocol produced no folds"
        raise DiagnosticFrameAssemblyError(detail)
    joined = (
        inputs.universe.filter(pl.col("eligible_for_new_risk"))
        .select(*_KEYS)
        .join(_value_column(inputs.size, _SIZE_FEATURE), on=_KEYS, how="left")
    )
    if feature_name != _SIZE_FEATURE:
        joined = joined.join(
            _value_column(inputs.feature, feature_name),
            on=_KEYS,
            how="left",
        )
    outputs: list[pl.DataFrame] = []
    preprocessor = FoldPreprocessor((feature_name,), _SIZE_FEATURE)
    for fold in folds:
        training = joined.filter(pl.col("decision_time").dt.date().is_in(fold.train))
        testing = joined.filter(pl.col("decision_time").dt.date().is_in(fold.test))
        artifact = preprocessor.fit(
            training,
            f"portfolio_fold_{fold.fold_index:03d}",
            dataset_snapshot_id,
        )
        outputs.append(
            preprocessor.transform(testing, artifact).select(
                *_KEYS,
                pl.col(feature_name).alias("factor_value"),
            )
        )
    result = pl.concat(outputs).sort(*_KEYS)
    if result.select(*_KEYS).is_duplicated().any():
        detail = "internal-test fold observation keys overlap"
        raise DiagnosticFrameAssemblyError(detail)
    return result


def build_oos_diagnostic_frame(
    inputs: DiagnosticFrameInputs,
    folds: tuple[WalkForwardFold, ...],
    *,
    feature_name: str,
    dataset_snapshot_id: str,
) -> pl.DataFrame:
    """Fit per-fold preprocessing and retain only disjoint internal-test rows."""
    if not folds:
        detail = "walk-forward protocol produced no folds"
        raise DiagnosticFrameAssemblyError(detail)
    joined = (
        inputs.universe.filter(pl.col("eligible_for_new_risk"))
        .select(*_KEYS)
        .join(_value_column(inputs.size, _SIZE_FEATURE), on=_KEYS, how="left")
        .join(_value_column(inputs.label, "label_value"), on=_KEYS, how="left")
    )
    if feature_name != _SIZE_FEATURE:
        joined = joined.join(
            _value_column(inputs.feature, feature_name),
            on=_KEYS,
            how="left",
        )
    outputs: list[pl.DataFrame] = []
    preprocessor = FoldPreprocessor((feature_name,), _SIZE_FEATURE)
    for fold in folds:
        training = joined.filter(pl.col("decision_time").dt.date().is_in(fold.train))
        testing = joined.filter(pl.col("decision_time").dt.date().is_in(fold.test))
        artifact = preprocessor.fit(
            training,
            f"diagnostic_fold_{fold.fold_index:03d}",
            dataset_snapshot_id,
        )
        transformed = preprocessor.transform(testing, artifact)
        outputs.append(
            transformed.select(
                *_KEYS,
                pl.col(feature_name).alias("factor_value"),
                "label_value",
                pl.col(_SIZE_FEATURE),
                pl.lit(None, dtype=pl.String).alias("industry"),
                pl.lit("UNAVAILABLE").alias("market_regime"),
            )
        )
    result = pl.concat(outputs).sort(*_KEYS)
    if result.select(*_KEYS).is_duplicated().any():
        detail = "internal-test fold observation keys overlap"
        raise DiagnosticFrameAssemblyError(detail)
    return result


def _value_column(frame: pl.DataFrame, name: str) -> pl.DataFrame:
    required = {*_KEYS, "value"}
    if not required.issubset(frame.columns):
        detail = f"{name} artifact has incomplete columns"
        raise DiagnosticFrameAssemblyError(detail)
    return frame.select(*_KEYS, pl.col("value").alias(name))
