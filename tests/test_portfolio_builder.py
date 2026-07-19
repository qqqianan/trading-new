from datetime import date

import pytest

from ashare_lab.domain.market import Symbol
from ashare_lab.portfolio.builder import (
    PortfolioBuilderConfig,
    PortfolioConstructionError,
    StandardizedFactorScore,
    TopNPortfolioBuilder,
)


def _scores(symbol_count: int = 40) -> tuple[StandardizedFactorScore, ...]:
    values: list[StandardizedFactorScore] = []
    for index in range(symbol_count):
        symbol = Symbol(f"{index:06d}.SZ")
        values.extend(
            (
                StandardizedFactorScore(symbol, "mom_20", float(index)),
                StandardizedFactorScore(symbol, "roe", float(index % 5)),
            )
        )
    return tuple(values)


def test_top_n_builder_creates_stable_equal_weight_target() -> None:
    # Given: forty symbols with complete standardized values for two candidate factors.
    builder = TopNPortfolioBuilder(
        PortfolioBuilderConfig(
            candidate_factor_names=("mom_20", "roe"),
            maximum_positions=30,
            target_gross_weight=0.95,
        )
    )

    # When: the weekly baseline target is constructed.
    target = builder.build(date(2024, 12, 27), "factor_baseline_v1", _scores())

    # Then: exactly Top 30 equal weights plus 5% cash sum to one.
    assert len(target.positions) == 30
    assert sum(item.weight for item in target.positions) + target.cash_weight == pytest.approx(1.0)
    assert target.cash_weight == pytest.approx(0.05)
    assert all(item.weight == pytest.approx(0.95 / 30) for item in target.positions)
    assert not hasattr(target, "orders")


def test_top_n_builder_breaks_equal_score_ties_by_symbol() -> None:
    # Given: thirty-one symbols with exactly equal composite scores.
    scores = tuple(
        StandardizedFactorScore(Symbol(f"{index:06d}.SZ"), "mom_20", 1.0) for index in range(31)
    )
    builder = TopNPortfolioBuilder(
        PortfolioBuilderConfig(("mom_20",), maximum_positions=30, target_gross_weight=0.95)
    )

    # When: the tied cross-section is ranked.
    target = builder.build(date(2024, 12, 27), "factor_baseline_v1", scores)

    # Then: lexical symbol order deterministically keeps the first thirty.
    assert tuple(str(item.symbol) for item in target.positions) == tuple(
        f"{index:06d}.SZ" for index in range(30)
    )


def test_top_n_builder_rejects_incomplete_factor_vector() -> None:
    # Given: one symbol is missing a required candidate factor.
    builder = TopNPortfolioBuilder(PortfolioBuilderConfig(("mom_20", "roe")))
    incomplete = (StandardizedFactorScore(Symbol("000001.SZ"), "mom_20", 1.0),)

    # When / Then: missing factors cannot receive a biased composite score.
    with pytest.raises(PortfolioConstructionError, match="complete"):
        builder.build(date(2024, 12, 27), "factor_baseline_v1", incomplete)


def test_top_n_builder_rejects_invalid_policy() -> None:
    # Given: a policy with no registered candidate factors.
    config = PortfolioBuilderConfig(())

    # When / Then: an unusable construction policy is rejected at creation.
    with pytest.raises(PortfolioConstructionError, match="valid"):
        TopNPortfolioBuilder(config)


def test_top_n_builder_rejects_duplicate_and_non_finite_values() -> None:
    # Given: duplicate and non-finite observations at the factor boundary.
    builder = TopNPortfolioBuilder(PortfolioBuilderConfig(("mom_20",)))
    duplicate = (
        StandardizedFactorScore(Symbol("000001.SZ"), "mom_20", 1.0),
        StandardizedFactorScore(Symbol("000001.SZ"), "mom_20", 2.0),
    )

    # When / Then: duplicates cannot silently replace an earlier observation.
    with pytest.raises(PortfolioConstructionError, match="duplicate"):
        builder.build(date(2024, 12, 27), "factor_baseline_v1", duplicate)


def test_top_n_builder_rejects_non_finite_candidate_value() -> None:
    # Given: one registered factor value is not finite.
    builder = TopNPortfolioBuilder(PortfolioBuilderConfig(("mom_20",)))
    scores = (StandardizedFactorScore(Symbol("000001.SZ"), "mom_20", float("nan")),)

    # When / Then: invalid numerical evidence cannot enter ranking.
    with pytest.raises(PortfolioConstructionError, match="non-finite"):
        builder.build(date(2024, 12, 27), "factor_baseline_v1", scores)
