"""Immutable evidence produced by market data integrity gates."""

from dataclasses import dataclass
from datetime import date

from ashare_lab.domain.market import PriceBasis


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """Auditable evidence produced by the mandatory data gate."""

    passed: bool
    bar_count: int
    first_date: date
    last_date: date
    price_basis: PriceBasis
    point_in_time: bool
    checks: tuple[str, ...]
