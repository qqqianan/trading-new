"""Leakage-resistant fitting and transformation for one walk-forward fold."""

from datetime import datetime
from typing import Final

import polars as pl

from ashare_lab.research.preprocessing.models import (
    FeatureFitStatistics,
    FoldPreprocessingArtifact,
)
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256

_TRANSFORM_VERSION: Final = "1.0.0"


class FoldPreprocessingError(Exception):
    """A fold cannot produce finite, auditable preprocessing parameters."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed preprocessing failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable boundary and concrete failure."""
        return f"fold_preprocessing: {self.detail}"


class FoldPreprocessor:
    """Fit global guards on training and apply same-time cross-sectional transforms."""

    def __init__(self, feature_names: tuple[str, ...], size_feature_name: str) -> None:
        """Bind an ordered feature contract and its size exposure column."""
        if not feature_names or len(feature_names) != len(set(feature_names)):
            detail = "feature names must be non-empty and unique"
            raise FoldPreprocessingError(detail)
        self._feature_names = feature_names
        self._size_feature_name = size_feature_name

    def fit(
        self,
        training: pl.DataFrame,
        fold_id: str,
        dataset_snapshot_id: str,
    ) -> FoldPreprocessingArtifact:
        """Learn winsor, fallback, and size coefficients from training rows only."""
        self._validate_frame(training)
        if training.is_empty():
            detail = "training fold cannot be empty"
            raise FoldPreprocessingError(detail)
        size_fallback = _finite_median(training[self._size_feature_name], self._size_feature_name)
        preliminary = tuple(self._fit_bounds(training, name) for name in self._feature_names)
        standardized = _standardize(
            training,
            preliminary,
            self._size_feature_name,
            size_fallback,
        )
        size_values = standardized[self._size_feature_name]
        statistics = tuple(
            _fit_feature_statistics(
                standardized,
                size_values,
                values,
                self._size_feature_name,
            )
            for values in preliminary
        )
        training_digest = training_frame_sha256(training)
        start = training["decision_time"].min()
        end = training["decision_time"].max()
        match start, end:
            case datetime() as start_time, datetime() as end_time:
                return FoldPreprocessingArtifact(
                    fold_id=fold_id,
                    dataset_snapshot_id=dataset_snapshot_id,
                    transform_version=_TRANSFORM_VERSION,
                    feature_names=self._feature_names,
                    size_feature_name=self._size_feature_name,
                    training_start=start_time,
                    training_end=end_time,
                    training_row_count=training.height,
                    training_data_sha256=training_digest,
                    size_fallback_median=size_fallback,
                    feature_statistics=statistics,
                    industry_neutralization_status="UNAVAILABLE",
                    industry_neutralization_reason=(
                        "PIT industry evidence does not cover the 2020-2025 research period"
                    ),
                )
            case _:
                detail = "training fold has invalid decision times"
                raise FoldPreprocessingError(detail)

    def transform(
        self,
        frame: pl.DataFrame,
        artifact: FoldPreprocessingArtifact,
    ) -> pl.DataFrame:
        """Apply immutable training parameters without fitting or deleting rows."""
        self._validate_frame(frame)
        if (
            artifact.feature_names != self._feature_names
            or artifact.size_feature_name != self._size_feature_name
        ):
            detail = "artifact feature contract differs from transformer"
            raise FoldPreprocessingError(detail)
        preliminary = tuple(
            (
                item.feature_name,
                item.lower_quantile,
                item.upper_quantile,
                item.fallback_median,
            )
            for item in artifact.feature_statistics
        )
        standardized = _standardize(
            frame,
            preliminary,
            self._size_feature_name,
            artifact.size_fallback_median,
        )
        expressions = tuple(
            (
                pl.col(item.feature_name)
                - item.neutralization_intercept
                - item.neutralization_slope * pl.col(self._size_feature_name)
            ).alias(item.feature_name)
            for item in artifact.feature_statistics
        )
        return standardized.with_columns(expressions)

    def _fit_bounds(
        self,
        training: pl.DataFrame,
        feature_name: str,
    ) -> tuple[str, float, float, float]:
        finite = training[feature_name].filter(training[feature_name].is_finite())
        lower = finite.quantile(0.01, interpolation="linear")
        upper = finite.quantile(0.99, interpolation="linear")
        match lower, upper:
            case float() as lower_value, float() as upper_value:
                fallback = _finite_median(finite.clip(lower_value, upper_value), feature_name)
                return feature_name, lower_value, upper_value, fallback
            case _:
                detail = f"{feature_name} has no finite training values"
                raise FoldPreprocessingError(detail)

    def _validate_frame(self, frame: pl.DataFrame) -> None:
        required = {"decision_time", "symbol", self._size_feature_name, *self._feature_names}
        missing = required.difference(frame.columns)
        if missing:
            detail = f"frame is missing columns: {sorted(missing)}"
            raise FoldPreprocessingError(detail)


def _standardize(
    frame: pl.DataFrame,
    preliminary: tuple[tuple[str, float, float, float], ...],
    size_feature_name: str,
    size_fallback: float,
) -> pl.DataFrame:
    feature_names = tuple(item[0] for item in preliminary)
    cleaned_names = (
        feature_names if size_feature_name in feature_names else (*feature_names, size_feature_name)
    )
    result = frame.with_columns(
        pl.when(pl.col(name).is_finite()).then(pl.col(name)).otherwise(None).alias(name)
        for name in cleaned_names
    )
    for name, lower, upper, fallback in preliminary:
        missing_name = f"{name}_missing"
        result = result.with_columns(pl.col(name).is_null().alias(missing_name))
        clipped = pl.col(name).clip(lower, upper)
        imputed = clipped.fill_null(clipped.median().over("decision_time")).fill_null(fallback)
        mean = imputed.mean().over("decision_time")
        standard_deviation = imputed.std(ddof=0).over("decision_time")
        result = result.with_columns(
            pl.when(standard_deviation > 0)
            .then((imputed - mean) / standard_deviation)
            .otherwise(0.0)
            .alias(name)
        )
    if size_feature_name in feature_names:
        return result
    size = pl.col(size_feature_name)
    size_imputed = size.fill_null(size.median().over("decision_time")).fill_null(size_fallback)
    size_mean = size_imputed.mean().over("decision_time")
    size_standard_deviation = size_imputed.std(ddof=0).over("decision_time")
    return result.with_columns(
        pl.when(size_standard_deviation > 0)
        .then((size_imputed - size_mean) / size_standard_deviation)
        .otherwise(0.0)
        .alias(size_feature_name)
    )


def _finite_median(series: pl.Series, feature_name: str) -> float:
    value = series.filter(series.is_finite()).median()
    match value:
        case float() as median:
            return median
        case _:
            detail = f"{feature_name} has no finite training median"
            raise FoldPreprocessingError(detail)


def _fit_feature_statistics(
    standardized: pl.DataFrame,
    size_values: pl.Series,
    preliminary: tuple[str, float, float, float],
    size_feature_name: str,
) -> FeatureFitStatistics:
    feature_name, lower, upper, fallback = preliminary
    if feature_name == size_feature_name:
        return FeatureFitStatistics(
            feature_name=feature_name,
            lower_quantile=lower,
            upper_quantile=upper,
            fallback_median=fallback,
            neutralization_intercept=0.0,
            neutralization_slope=0.0,
        )
    feature_values = standardized[feature_name]
    size_mean = size_values.mean()
    feature_mean = feature_values.mean()
    variance = ((size_values - size_mean) ** 2).mean()
    covariance = ((size_values - size_mean) * (feature_values - feature_mean)).mean()
    match size_mean, feature_mean, variance, covariance:
        case float() as x_mean, float() as y_mean, float() as x_var, float() as covariance_value:
            slope = 0.0 if x_var == 0 else covariance_value / x_var
            return FeatureFitStatistics(
                feature_name=feature_name,
                lower_quantile=lower,
                upper_quantile=upper,
                fallback_median=fallback,
                neutralization_intercept=y_mean - slope * x_mean,
                neutralization_slope=slope,
            )
        case _:
            detail = f"{feature_name} neutralization is not finite"
            raise FoldPreprocessingError(detail)
