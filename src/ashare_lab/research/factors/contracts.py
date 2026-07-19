"""Internal typed inputs for an audited factor research batch."""

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True, slots=True)
class FactorDiagnosticInput:
    """One registered trial and its development-only joined diagnostic frame."""

    trial_id: str
    frame: pl.DataFrame
