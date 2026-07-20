from pathlib import Path

import polars as pl
import pytest

from ashare_lab.portfolio.research_models import (
    PortfolioTargetBatch,
)
from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.factors.models import ExpectedDirection, FactorFamily
from ashare_lab.research.factors.runtime_frames import (
    ScoreFrameInputs,
    build_oos_score_frame,
)
from ashare_lab.research.factors.runtime_source import ArtifactFactorScoreSource
from ashare_lab.services.portfolio_research import (
    PortfolioBuildRequest,
    PortfolioResearchError,
    build_portfolio_targets,
)
from ashare_lab.services.portfolio_runtime import (
    PortfolioRuntimeError,
    run_default_portfolio_targets,
)

from .test_factor_runtime import factor_runtime_fixture
from .training_support import folds, training_frame


def test_portfolio_score_frame_is_physically_label_free() -> None:
    # Given: governed universe, feature, and size rows with no label capability.
    frame = training_frame()
    inputs = ScoreFrameInputs(
        universe=frame.select("decision_time", "symbol").with_columns(
            pl.lit(value=True).alias("eligible_for_new_risk")
        ),
        feature=frame.select("decision_time", "symbol", pl.col("factor_a").alias("value")),
        size=frame.select("decision_time", "symbol", pl.col("log_total_mv").alias("value")),
    )

    # When: fold-local preprocessing builds internal-test portfolio scores.
    result = build_oos_score_frame(
        inputs,
        folds(),
        feature_name="factor_a",
        dataset_snapshot_id="ds_abc123",
    )

    # Then: only keys and standardized score cross the portfolio boundary.
    assert result.columns == ["decision_time", "symbol", "factor_value"]
    assert result.height == 16
    assert result["factor_value"].is_finite().all()


def test_artifact_score_source_never_reads_label_artifact() -> None:
    # Given: a DatasetSpec whose verified reader records every physical access.
    spec, trial, reader, calendar = factor_runtime_fixture()
    source = ArtifactFactorScoreSource(reader, spec, calendar)

    # When: one registered candidate loads its internal-test scores.
    result = source.load(trial)

    # Then: the score frame is complete and no label capability was exercised.
    assert result.height == 78
    assert result.columns == ["decision_time", "symbol", "factor_value"]
    assert ArtifactKind.LABEL not in {kind for kind, _artifact_id in reader.calls}


class MemoryScoreSource:
    """Small real score source with no label method or state."""

    def __init__(self, frames: dict[str, pl.DataFrame]) -> None:
        self._frames = frames

    def load(self, trial: FactorTrial) -> pl.DataFrame:
        return self._frames[trial.feature_name]


def _trial(name: str, direction: ExpectedDirection) -> FactorTrial:
    identity = "a" if name == "factor_a" else "b"
    return FactorTrial(
        trial_id="factor_trial_" + identity * 64,
        dataset_snapshot_id="ds_abc123",
        feature_name=name,
        feature_version="1.0.0",
        feature_artifact_id="feature_artifact_" + identity * 64,
        family=FactorFamily.VALUE,
        expected_direction=direction,
        simplicity_rank=0,
        diagnostic_version="1.0.0",
    )


def test_real_portfolio_targets_orient_candidates_and_keep_top_30() -> None:
    # Given: two complete label-free candidate frames over two decision dates.
    dates = folds()[0].test[:2]
    rows = tuple((day, f"{index:06d}.SZ", float(index)) for day in dates for index in range(40))
    source = MemoryScoreSource(
        {
            "factor_a": pl.DataFrame(
                rows,
                schema=("decision_time", "symbol", "factor_value"),
                orient="row",
            ),
            "factor_b": pl.DataFrame(
                tuple((day, symbol, -value) for day, symbol, value in rows),
                schema=("decision_time", "symbol", "factor_value"),
                orient="row",
            ),
        }
    )
    request = PortfolioBuildRequest(
        factor_report_id="factor_report_" + "c" * 64,
        dataset_snapshot_id="ds_abc123",
        trial_batch_id="trial_batch_" + "d" * 64,
        candidate_trials=(
            _trial("factor_a", ExpectedDirection.HIGHER_IS_BETTER),
            _trial("factor_b", ExpectedDirection.LOWER_IS_BETTER),
        ),
    )

    # When: the equal-factor weekly baseline is materialized.
    result = build_portfolio_targets(request, source)

    # Then: both directions favor the highest thirty symbols without order authority.
    assert len(result.records) == 2
    assert result.candidate_factor_names == ("factor_a", "factor_b")
    assert tuple(item.symbol for item in result.records[0].positions) == tuple(
        f"{index:06d}.SZ" for index in range(39, 9, -1)
    )
    assert not hasattr(result.records[0], "orders")


def _single_factor_batch() -> PortfolioTargetBatch:
    dates = folds()[0].test[:1]
    frame = pl.DataFrame(
        tuple((day, f"{index:06d}.SZ", float(index)) for day in dates for index in range(40)),
        schema=("decision_time", "symbol", "factor_value"),
        orient="row",
    )
    request = PortfolioBuildRequest(
        factor_report_id="factor_report_" + "c" * 64,
        dataset_snapshot_id="ds_abc123",
        trial_batch_id="trial_batch_" + "d" * 64,
        candidate_trials=(_trial("factor_a", ExpectedDirection.HIGHER_IS_BETTER),),
    )
    return build_portfolio_targets(request, MemoryScoreSource({"factor_a": frame}))


def test_portfolio_research_rejects_mismatched_candidate_keys() -> None:
    # Given: two candidates whose second frame silently omits one security.
    day = folds()[0].test[0]
    first = pl.DataFrame(
        ((day, "000001.SZ", 1.0), (day, "000002.SZ", 2.0)),
        schema=("decision_time", "symbol", "factor_value"),
        orient="row",
    )
    source = MemoryScoreSource({"factor_a": first, "factor_b": first.head(1)})
    request = PortfolioBuildRequest(
        factor_report_id="factor_report_" + "c" * 64,
        dataset_snapshot_id="ds_abc123",
        trial_batch_id="trial_batch_" + "d" * 64,
        candidate_trials=(
            _trial("factor_a", ExpectedDirection.HIGHER_IS_BETTER),
            _trial("factor_b", ExpectedDirection.LOWER_IS_BETTER),
        ),
    )

    # When / Then: inner-join sample deletion is rejected explicitly.
    with pytest.raises(PortfolioResearchError, match="keys differ"):
        build_portfolio_targets(request, source)


def test_portfolio_runtime_reports_missing_factor_report(tmp_path: Path) -> None:
    # Given: a project artifact root without the requested report identity.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: the composition root returns a stable blocker.
    with pytest.raises(PortfolioRuntimeError, match="portfolio_runtime"):
        run_default_portfolio_targets(tmp_path, "factor_report_" + "a" * 64)
