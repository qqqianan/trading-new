from datetime import date

import polars as pl
import pytest

from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.factors.models import ExpectedDirection, FactorFamily
from ashare_lab.services.portfolio_research import (
    PortfolioBuildRequest,
    PortfolioResearchError,
    build_portfolio_targets,
)


class MemorySource:
    """Minimal score source for portfolio contract rejection tests."""

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame

    def load(self, trial: FactorTrial) -> pl.DataFrame:
        if trial.feature_name != "factor_a":
            message = f"unexpected trial: {trial.feature_name}"
            raise AssertionError(message)
        return self._frame


def _trial(dataset_id: str = "ds_abc123") -> FactorTrial:
    return FactorTrial(
        trial_id="factor_trial_" + "a" * 64,
        dataset_snapshot_id=dataset_id,
        feature_name="factor_a",
        feature_version="1.0.0",
        feature_artifact_id="feature_artifact_" + "b" * 64,
        family=FactorFamily.VALUE,
        expected_direction=ExpectedDirection.HIGHER_IS_BETTER,
        simplicity_rank=0,
        diagnostic_version="1.0.0",
    )


def _request(trials: tuple[FactorTrial, ...]) -> PortfolioBuildRequest:
    return PortfolioBuildRequest(
        factor_report_id="factor_report_" + "c" * 64,
        dataset_snapshot_id="ds_abc123",
        trial_batch_id="trial_batch_" + "d" * 64,
        candidate_trials=trials,
    )


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        ((date(2024, 10, 11), "000001.SZ", 1.0),),
        schema=("decision_time", "symbol", "factor_value"),
        orient="row",
    )


def test_portfolio_research_rejects_empty_candidates() -> None:
    # Given / When / Then: a report with no candidate cannot publish a portfolio.
    with pytest.raises(PortfolioResearchError, match="non-empty"):
        build_portfolio_targets(_request(()), MemorySource(_frame()))


def test_portfolio_research_rejects_cross_dataset_trial() -> None:
    # Given / When / Then: candidates cannot cross the selected DatasetSpec.
    with pytest.raises(PortfolioResearchError, match="DatasetSpec"):
        build_portfolio_targets(_request((_trial("ds_deadbeef"),)), MemorySource(_frame()))


def test_portfolio_research_rejects_incomplete_score_columns() -> None:
    # Given: a candidate frame without its standardized value.
    incomplete = _frame().drop("factor_value")

    # When / Then: incomplete physical score evidence fails closed.
    with pytest.raises(PortfolioResearchError, match="columns are incomplete"):
        build_portfolio_targets(_request((_trial(),)), MemorySource(incomplete))


def test_portfolio_research_rejects_duplicate_score_keys() -> None:
    # Given: one candidate repeats the same symbol and decision key.
    duplicated = pl.concat((_frame(), _frame()))

    # When / Then: no duplicate can receive an arbitrary replacement value.
    with pytest.raises(PortfolioResearchError, match="keys are duplicated"):
        build_portfolio_targets(_request((_trial(),)), MemorySource(duplicated))
