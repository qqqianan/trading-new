"""Protocol-bound factor-primary portfolio construction with a Ridge veto."""

from dataclasses import dataclass
from datetime import date
from math import ceil

import polars as pl
from pydantic import TypeAdapter

from ashare_lab.portfolio.research_models import (
    PortfolioTargetBatch,
    PortfolioTargetPositionRow,
    PortfolioTargetRecord,
)
from ashare_lab.research.experiments.portfolio_protocol_models import (
    PortfolioExperimentProtocol,
)

_DATES = TypeAdapter(tuple[date, ...])
_SYMBOLS = TypeAdapter(tuple[str, ...])
_VALUES = TypeAdapter(tuple[float, ...])
_KEYS = ("decision_time", "symbol")


class PortfolioVetoResearchError(Exception):
    """Label-free factor and model scores cannot form protocol-bound targets."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable construction blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the research boundary and concrete blocker."""
        return f"portfolio_veto_research: {self.detail}"


@dataclass(frozen=True, slots=True)
class FactorAnchorVetoBuildRequest:
    """Exact protocol and factor lineage admitted to target construction."""

    protocol: PortfolioExperimentProtocol
    factor_report_id: str
    trial_batch_id: str
    candidate_factor_names: tuple[str, ...]


def build_factor_anchor_veto_targets(
    request: FactorAnchorVetoBuildRequest,
    factor_scores: pl.DataFrame,
    model_scores: pl.DataFrame,
) -> PortfolioTargetBatch:
    """Apply the frozen veto before factor-primary Top30 selection."""
    _validate_inputs(request, factor_scores, model_scores)
    joined = factor_scores.join(model_scores, on=list(_KEYS), how="inner", validate="1:1")
    dates = _DATES.validate_python(joined["decision_time"].dt.date().unique().sort().to_list())
    records = tuple(_build_record(day, joined, request.protocol) for day in dates)
    return PortfolioTargetBatch(
        factor_report_id=request.factor_report_id,
        model_id=request.protocol.parent_model_id,
        portfolio_protocol_id=request.protocol.protocol_id,
        dataset_snapshot_id=request.protocol.dataset_snapshot_id,
        trial_batch_id=request.trial_batch_id,
        portfolio_rule_version="3.0.0",
        evidence_classification="REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE",
        candidate_factor_names=(
            *request.candidate_factor_names,
            "ridge_bottom_quintile_veto",
        ),
        records=records,
    )


def _validate_inputs(
    request: FactorAnchorVetoBuildRequest,
    factor_scores: pl.DataFrame,
    model_scores: pl.DataFrame,
) -> None:
    protocol = request.protocol
    if (
        protocol.status != "PREREGISTERED_NOT_IMPLEMENTED"
        or protocol.evidence_classification != "REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE"
        or protocol.fresh_forward.final_holdout_access_permitted
        or not request.candidate_factor_names
        or len(request.candidate_factor_names) != len(set(request.candidate_factor_names))
    ):
        detail = "protocol or candidate factor lineage is not eligible for implementation"
        raise PortfolioVetoResearchError(detail)
    if factor_scores.columns != [*_KEYS, "factor_score"] or model_scores.columns != [
        *_KEYS,
        "model_score",
    ]:
        detail = "factor and model score frames must contain exact columns"
        raise PortfolioVetoResearchError(detail)
    if factor_scores.is_empty() or model_scores.is_empty():
        detail = "factor and model score frames must be non-empty"
        raise PortfolioVetoResearchError(detail)
    if (
        factor_scores.select(*_KEYS).is_duplicated().any()
        or model_scores.select(*_KEYS).is_duplicated().any()
    ):
        detail = "factor and model score keys must be unique"
        raise PortfolioVetoResearchError(detail)
    left = factor_scores.select(*_KEYS).sort(*_KEYS)
    right = model_scores.select(*_KEYS).sort(*_KEYS)
    if not left.equals(right):
        detail = "factor and model score keys differ"
        raise PortfolioVetoResearchError(detail)
    if (
        not factor_scores.select(pl.col("factor_score").is_finite().all()).item()
        or not model_scores.select(pl.col("model_score").is_finite().all()).item()
    ):
        detail = "factor and model scores must be finite"
        raise PortfolioVetoResearchError(detail)


def _build_record(
    day: date,
    scores: pl.DataFrame,
    protocol: PortfolioExperimentProtocol,
) -> PortfolioTargetRecord:
    daily = scores.filter(pl.col("decision_time").dt.date() == day)
    veto_count = ceil(daily.height * protocol.candidate_rule.veto_quantile)
    vetoed = set(
        _SYMBOLS.validate_python(
            daily.sort("model_score", "symbol").head(veto_count)["symbol"].to_list()
        )
    )
    survivors = daily.filter(~pl.col("symbol").is_in(vetoed)).sort(
        "factor_score",
        "symbol",
        descending=[True, False],
    )
    maximum = protocol.candidate_rule.maximum_positions
    if survivors.height < maximum:
        detail = f"only {survivors.height} securities survive the protocol veto"
        raise PortfolioVetoResearchError(detail)
    selected = survivors.head(maximum)
    symbols = _SYMBOLS.validate_python(selected["symbol"].to_list())
    values = _VALUES.validate_python(selected["factor_score"].to_list())
    weight = protocol.candidate_rule.target_gross_weight / maximum
    return PortfolioTargetRecord(
        decision_date=day,
        positions=tuple(
            PortfolioTargetPositionRow(symbol=symbol, target_weight=weight, score=value)
            for symbol, value in zip(symbols, values, strict=True)
        ),
        cash_weight=protocol.candidate_rule.cash_weight,
    )
