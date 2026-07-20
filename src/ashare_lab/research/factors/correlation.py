"""Same-family cross-factor correlation evidence for deterministic redundancy."""

import polars as pl
from pydantic import Field, field_validator

from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.factors.contracts import FactorDiagnosticInput
from ashare_lab.research.factors.models import FrozenFactorModel, stable_metric


class FactorCorrelation(FrozenFactorModel):
    """Observed development correlation between two registered factor trials."""

    left_trial_id: str = Field(min_length=1)
    right_trial_id: str = Field(min_length=1)
    correlation: float = Field(ge=-1, le=1, allow_inf_nan=False)

    @field_validator("correlation")
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Stabilize redundancy decisions across parallel reductions."""
        return stable_metric(value)


def same_family_correlations(
    inputs: tuple[FactorDiagnosticInput, ...],
    trials: tuple[FactorTrial, ...],
) -> tuple[FactorCorrelation, ...]:
    """Compute pairwise same-date rank correlation only within predefined families."""
    frames = {item.trial_id: item.frame for item in inputs}
    evidence: list[FactorCorrelation] = []
    for left_index, left in enumerate(trials):
        for right in trials[left_index + 1 :]:
            if left.family is not right.family:
                continue
            correlation = _pair_correlation(frames[left.trial_id], frames[right.trial_id])
            evidence.append(
                FactorCorrelation(
                    left_trial_id=left.trial_id,
                    right_trial_id=right.trial_id,
                    correlation=correlation,
                )
            )
    return tuple(evidence)


def _pair_correlation(left: pl.DataFrame, right: pl.DataFrame) -> float:
    left_values = left.select(
        "decision_time",
        "symbol",
        pl.col("factor_value").alias("left_value"),
    )
    right_values = right.select(
        "decision_time",
        "symbol",
        pl.col("factor_value").alias("right_value"),
    )
    daily = (
        left_values.join(right_values, on=["decision_time", "symbol"])
        .filter(
            pl.col("left_value").is_not_null()
            & pl.col("left_value").is_finite()
            & pl.col("right_value").is_not_null()
            & pl.col("right_value").is_finite()
        )
        .with_columns(
            pl.col("left_value").rank("average").over("decision_time").alias("left_rank"),
            pl.col("right_value").rank("average").over("decision_time").alias("right_rank"),
        )
        .group_by("decision_time")
        .agg(pl.corr("left_rank", "right_rank").alias("correlation"))
        .filter(pl.col("correlation").is_finite())
    )
    value = daily["correlation"].mean()
    match value:
        case float() as result:
            return max(-1.0, min(1.0, result))
        case int() as result:
            return max(-1.0, min(1.0, float(result)))
        case _:
            return 0.0
