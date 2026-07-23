from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.experiments.portfolio_protocol_identity import (
    create_factor_anchor_veto_protocol,
)
from ashare_lab.services.portfolio_veto_research import (
    FactorAnchorVetoBuildRequest,
    PortfolioVetoResearchError,
    build_factor_anchor_veto_targets,
)

from .test_portfolio_protocol import portfolio_protocol_request_fixture


def _scores(count: int = 40) -> tuple[pl.DataFrame, pl.DataFrame]:
    day = datetime(2024, 1, 5, 18, tzinfo=ZoneInfo("Asia/Shanghai"))
    symbols = tuple(f"{index:06d}.SZ" for index in range(count))
    factor = pl.DataFrame(
        {"decision_time": [day] * count, "symbol": symbols, "factor_score": range(count)}
    )
    model = pl.DataFrame(
        {"decision_time": [day] * count, "symbol": symbols, "model_score": range(count)}
    )
    return factor, model


def _request() -> FactorAnchorVetoBuildRequest:
    protocol = create_factor_anchor_veto_protocol(portfolio_protocol_request_fixture())
    return FactorAnchorVetoBuildRequest(
        protocol=protocol,
        factor_report_id="factor_report_" + "c" * 64,
        trial_batch_id="trial_batch_" + "d" * 64,
        candidate_factor_names=("factor_a", "factor_b"),
    )


def test_veto_builder_uses_ceiling_and_stable_model_score_order() -> None:
    # Given: 41 stocks whose lowest model scores are also highest factor scores.
    factor, model = _scores(41)
    factor = factor.with_columns((-pl.col("factor_score")).alias("factor_score"))

    # When: the preregistered bottom-quintile veto is applied.
    targets = build_factor_anchor_veto_targets(_request(), factor, model)

    # Then: ceil(41*20%) removes symbols 0..8 before factor ranking selects thirty.
    selected = tuple(item.symbol for item in targets.records[0].positions)
    assert selected == tuple(f"{index:06d}.SZ" for index in range(9, 39))
    assert targets.portfolio_protocol_id == _request().protocol.protocol_id
    assert targets.evidence_classification == "REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE"
    assert targets.portfolio_rule_version == "3.0.0"


def test_veto_builder_breaks_equal_model_scores_by_symbol_ascending() -> None:
    # Given: forty equal model scores and factor scores favoring the smallest symbols.
    factor, model = _scores()
    factor = factor.with_columns((-pl.col("factor_score")).alias("factor_score"))
    model = model.with_columns(pl.lit(0.0).alias("model_score"))

    # When: deterministic veto ordering resolves the model ties.
    targets = build_factor_anchor_veto_targets(_request(), factor, model)

    # Then: symbols 0..7 are vetoed and cannot re-enter through factor ranking.
    selected = tuple(item.symbol for item in targets.records[0].positions)
    assert selected == tuple(f"{index:06d}.SZ" for index in range(8, 38))


def test_veto_builder_rejects_mismatched_score_keys() -> None:
    # Given: the model score stream silently omits one factor-score observation.
    factor, model = _scores()

    # When / Then: no favorable inner intersection may define the candidate universe.
    with pytest.raises(PortfolioVetoResearchError, match="keys differ"):
        build_factor_anchor_veto_targets(_request(), factor, model.head(39))


def test_veto_builder_rejects_label_capability() -> None:
    # Given: a factor score stream contaminated with a future label column.
    factor, model = _scores()
    contaminated = factor.with_columns(pl.lit(0.1).alias("label_value"))

    # When / Then: only the two registered label-free score boundaries are accepted.
    with pytest.raises(PortfolioVetoResearchError, match="exact columns"):
        build_factor_anchor_veto_targets(_request(), contaminated, model)


def test_veto_builder_rejects_duplicate_score_keys() -> None:
    # Given: one Ridge prediction key is present twice.
    factor, model = _scores()
    duplicated = pl.concat((model, model.head(1)))

    # When / Then: duplicate observations cannot influence the veto count.
    with pytest.raises(PortfolioVetoResearchError, match="keys must be unique"):
        build_factor_anchor_veto_targets(_request(), factor, duplicated)


def test_veto_builder_rejects_non_finite_scores() -> None:
    # Given: one factor score is non-finite at the portfolio boundary.
    factor, model = _scores()
    non_finite = factor.with_columns(
        pl.when(pl.col("symbol") == "000000.SZ")
        .then(float("nan"))
        .otherwise(pl.col("factor_score"))
        .alias("factor_score")
    )

    # When / Then: an invalid score cannot enter deterministic ranking.
    with pytest.raises(PortfolioVetoResearchError, match="scores must be finite"):
        build_factor_anchor_veto_targets(_request(), non_finite, model)


def test_veto_builder_rejects_insufficient_survivors() -> None:
    # Given: thirty-seven securities leave only twenty-nine after the 20% veto.
    factor, model = _scores(37)

    # When / Then: the protocol cannot silently publish a smaller portfolio.
    with pytest.raises(PortfolioVetoResearchError, match="only 29 securities survive"):
        build_factor_anchor_veto_targets(_request(), factor, model)
