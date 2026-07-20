"""Benjamini-Hochberg false-discovery correction over every disclosed trial."""

from pydantic import Field, field_validator

from ashare_lab.research.factors.models import FrozenFactorModel, stable_metric


class PValueObservation(FrozenFactorModel):
    """One registered trial and its unadjusted diagnostic p-value."""

    trial_id: str = Field(min_length=1)
    p_value: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("p_value")
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze p-value precision before FDR ordering."""
        return stable_metric(value)


class FdrResult(FrozenFactorModel):
    """One BH-adjusted q-value retained in original ledger order."""

    trial_id: str
    p_value: float
    q_value: float
    significant: bool

    @field_validator("p_value", "q_value")
    @classmethod
    def normalize_metric(cls, value: float) -> float:
        """Freeze persisted multiple-testing metrics."""
        return stable_metric(value)


def benjamini_hochberg(
    observations: tuple[PValueObservation, ...],
    maximum_q: float,
) -> tuple[FdrResult, ...]:
    """Adjust all disclosed p-values without dropping failed trials."""
    if not 0 < maximum_q <= 1:
        detail = "maximum_q must be in (0, 1]"
        raise MultipleTestingError(detail)
    if not observations:
        return ()
    ordered = tuple(sorted(observations, key=lambda item: (item.p_value, item.trial_id)))
    count = len(ordered)
    adjusted_reversed: list[float] = []
    running = 1.0
    for reverse_index, item in enumerate(reversed(ordered)):
        rank = count - reverse_index
        running = min(running, item.p_value * count / rank, 1.0)
        adjusted_reversed.append(running)
    adjusted = tuple(reversed(adjusted_reversed))
    q_by_trial = {item.trial_id: q_value for item, q_value in zip(ordered, adjusted, strict=True)}
    return tuple(
        FdrResult(
            trial_id=item.trial_id,
            p_value=item.p_value,
            q_value=q_by_trial[item.trial_id],
            significant=q_by_trial[item.trial_id] <= maximum_q,
        )
        for item in observations
    )


class MultipleTestingError(Exception):
    """A false-discovery control configuration is invalid."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed multiple-testing failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the rejected correction detail."""
        return f"multiple_testing: {self.detail}"
