"""Deterministic equal-factor Top-N portfolio target construction."""

from dataclasses import dataclass
from datetime import date
from math import isfinite

from ashare_lab.domain.market import Symbol
from ashare_lab.portfolio.contracts import PortfolioTarget, TargetPosition


@dataclass(frozen=True, slots=True)
class StandardizedFactorScore:
    """One fold-preprocessed candidate factor value for one security."""

    symbol: Symbol
    factor_name: str
    value: float


@dataclass(frozen=True, slots=True)
class PortfolioBuilderConfig:
    """Frozen baseline composition rules shared by every score source."""

    candidate_factor_names: tuple[str, ...]
    maximum_positions: int = 30
    target_gross_weight: float = 0.95


class PortfolioConstructionError(Exception):
    """Candidate scores cannot form a complete deterministic target."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed portfolio construction failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the construction boundary and concrete failure."""
        return f"portfolio_construction: {self.detail}"


class TopNPortfolioBuilder:
    """Average standardized candidate factors and emit target weights only."""

    def __init__(self, config: PortfolioBuilderConfig) -> None:
        """Bind one immutable baseline construction policy."""
        names = config.candidate_factor_names
        if (
            not names
            or len(names) != len(set(names))
            or config.maximum_positions <= 0
            or not 0 < config.target_gross_weight < 1
        ):
            detail = "candidate factors, position count, and gross weight must be valid"
            raise PortfolioConstructionError(detail)
        self._config = config

    def build(
        self,
        decision_date: date,
        signal_source_id: str,
        scores: tuple[StandardizedFactorScore, ...],
    ) -> PortfolioTarget:
        """Create a stable equal-weight target without orders or execution authority."""
        values: dict[Symbol, dict[str, float]] = {}
        candidates = set(self._config.candidate_factor_names)
        for item in scores:
            if item.factor_name not in candidates:
                continue
            if not isfinite(item.value):
                detail = f"non-finite score for {item.symbol}:{item.factor_name}"
                raise PortfolioConstructionError(detail)
            symbol_values = values.setdefault(item.symbol, {})
            if item.factor_name in symbol_values:
                detail = f"duplicate score for {item.symbol}:{item.factor_name}"
                raise PortfolioConstructionError(detail)
            symbol_values[item.factor_name] = item.value
        expected = set(self._config.candidate_factor_names)
        if not values or any(set(item) != expected for item in values.values()):
            detail = "every security must have a complete candidate factor vector"
            raise PortfolioConstructionError(detail)
        composite = tuple(
            (symbol, sum(item.values()) / len(self._config.candidate_factor_names))
            for symbol, item in values.items()
        )
        selected = tuple(
            sorted(composite, key=lambda item: (-item[1], str(item[0])))[
                : self._config.maximum_positions
            ]
        )
        weight = self._config.target_gross_weight / len(selected)
        positions = tuple(
            TargetPosition(symbol=symbol, weight=weight, score=score) for symbol, score in selected
        )
        gross = sum(item.weight for item in positions)
        return PortfolioTarget(
            decision_date=decision_date,
            model_id=signal_source_id,
            positions=positions,
            cash_weight=1.0 - gross,
        )
