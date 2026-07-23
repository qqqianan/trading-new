"""Label-free construction of complete development portfolio targets."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import polars as pl
from pydantic import TypeAdapter

from ashare_lab.domain.market import Symbol
from ashare_lab.portfolio.builder import (
    PortfolioBuilderConfig,
    StandardizedFactorScore,
    TopNPortfolioBuilder,
)
from ashare_lab.portfolio.research_models import (
    PortfolioTargetBatch,
    PortfolioTargetPositionRow,
    PortfolioTargetRecord,
)
from ashare_lab.research.experiments.trial_ledger import FactorTrial

_KEYS = ("decision_time", "symbol")
_DATES = TypeAdapter(tuple[date, ...])
_SYMBOLS = TypeAdapter(tuple[str, ...])
_VALUES = TypeAdapter(tuple[float, ...])


class PortfolioScoreFrameSource(Protocol):
    """Read one label-free, fold-preprocessed candidate score frame."""

    def load(self, trial: FactorTrial) -> pl.DataFrame:
        """Return exact keys and standardized factor values."""
        ...


@dataclass(frozen=True, slots=True)
class PortfolioBuildRequest:
    """Verified report identity and its ordered candidate trials."""

    factor_report_id: str
    dataset_snapshot_id: str
    trial_batch_id: str
    candidate_trials: tuple[FactorTrial, ...]


@dataclass(frozen=True, slots=True)
class ModelPortfolioBuildRequest:
    """One keyed model score stream and its complete research lineage."""

    model_id: str
    factor_report_id: str
    dataset_snapshot_id: str
    trial_batch_id: str


@dataclass(frozen=True, slots=True)
class FactorCompositeScores:
    """Label-free equal-factor composite with its ordered source names."""

    candidate_factor_names: tuple[str, ...]
    frame: pl.DataFrame


class PortfolioResearchError(Exception):
    """Candidate score artifacts cannot form an auditable target batch."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable portfolio research failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the research boundary and concrete blocker."""
        return f"portfolio_research: {self.detail}"


def build_portfolio_targets(
    request: PortfolioBuildRequest,
    source: PortfolioScoreFrameSource,
) -> PortfolioTargetBatch:
    """Orient registered candidates and build every internal-test Top 30 target."""
    composite = build_factor_composite_scores(request, source)
    name = "factor_score"
    wide = composite.frame
    builder = TopNPortfolioBuilder(PortfolioBuilderConfig((name,)))
    dates = _DATES.validate_python(wide["decision_time"].dt.date().unique().sort().to_list())
    records = tuple(
        _build_record(day, wide, (name,), builder, request.factor_report_id) for day in dates
    )
    return PortfolioTargetBatch(
        factor_report_id=request.factor_report_id,
        dataset_snapshot_id=request.dataset_snapshot_id,
        trial_batch_id=request.trial_batch_id,
        candidate_factor_names=composite.candidate_factor_names,
        records=records,
    )


def build_factor_composite_scores(
    request: PortfolioBuildRequest,
    source: PortfolioScoreFrameSource,
) -> FactorCompositeScores:
    """Orient registered factors and expose their complete label-free composite."""
    trials = request.candidate_trials
    names = tuple(trial.feature_name for trial in trials)
    if not trials or len(names) != len(set(names)):
        detail = "candidate trials must be non-empty and unique"
        raise PortfolioResearchError(detail)
    if any(trial.dataset_snapshot_id != request.dataset_snapshot_id for trial in trials):
        detail = "candidate trial crosses DatasetSpec boundary"
        raise PortfolioResearchError(detail)
    wide: pl.DataFrame | None = None
    for trial in trials:
        frame = source.load(trial)
        if not {*_KEYS, "factor_value"}.issubset(frame.columns):
            detail = f"candidate score columns are incomplete: {trial.feature_name}"
            raise PortfolioResearchError(detail)
        if frame.select(*_KEYS).is_duplicated().any():
            detail = f"candidate score keys are duplicated: {trial.feature_name}"
            raise PortfolioResearchError(detail)
        oriented = frame.select(
            *_KEYS,
            (pl.col("factor_value") * trial.expected_direction.multiplier).alias(
                trial.feature_name
            ),
        )
        if wide is None:
            wide = oriented
            continue
        expected_rows = wide.height
        wide = wide.join(oriented, on=_KEYS, how="inner", validate="1:1")
        if wide.height != expected_rows or oriented.height != expected_rows:
            detail = f"candidate score keys differ: {trial.feature_name}"
            raise PortfolioResearchError(detail)
    if wide is None:
        detail = "candidate score matrix is absent"
        raise PortfolioResearchError(detail)
    return FactorCompositeScores(
        candidate_factor_names=names,
        frame=wide.select(
            *_KEYS,
            pl.mean_horizontal(*names).alias("factor_score"),
        ),
    )


def build_model_portfolio_targets(
    request: ModelPortfolioBuildRequest,
    scores: pl.DataFrame,
) -> PortfolioTargetBatch:
    """Build model-ranked Top 30 targets without reading labels or creating orders."""
    expected_columns = [*_KEYS, "model_score"]
    if scores.columns != expected_columns or scores.is_empty():
        detail = "model score frame must contain only exact keys and model_score"
        raise PortfolioResearchError(detail)
    if scores.select(*_KEYS).is_duplicated().any():
        detail = "model score keys are duplicated"
        raise PortfolioResearchError(detail)
    name = "model_prediction"
    wide = scores.rename({"model_score": name})
    builder = TopNPortfolioBuilder(PortfolioBuilderConfig((name,)))
    dates = _DATES.validate_python(wide["decision_time"].dt.date().unique().sort().to_list())
    records = tuple(_build_record(day, wide, (name,), builder, request.model_id) for day in dates)
    return PortfolioTargetBatch(
        factor_report_id=request.factor_report_id,
        model_id=request.model_id,
        dataset_snapshot_id=request.dataset_snapshot_id,
        trial_batch_id=request.trial_batch_id,
        portfolio_rule_version="2.0.0",
        candidate_factor_names=(name,),
        records=records,
    )


def _build_record(
    day: date,
    wide: pl.DataFrame,
    names: tuple[str, ...],
    builder: TopNPortfolioBuilder,
    signal_source_id: str,
) -> PortfolioTargetRecord:
    daily = wide.filter(pl.col("decision_time").dt.date() == day).sort("symbol")
    symbols = _SYMBOLS.validate_python(daily["symbol"].to_list())
    scores = tuple(
        StandardizedFactorScore(Symbol(symbol), name, value)
        for name in names
        for symbol, value in zip(
            symbols,
            _VALUES.validate_python(daily[name].to_list()),
            strict=True,
        )
    )
    target = builder.build(day, signal_source_id, scores)
    return PortfolioTargetRecord(
        decision_date=day,
        positions=tuple(
            PortfolioTargetPositionRow(
                symbol=str(item.symbol),
                target_weight=item.weight,
                score=item.score,
            )
            for item in target.positions
        ),
        cash_weight=target.cash_weight,
    )
