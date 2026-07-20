from pathlib import Path

import polars as pl
import pytest

from ashare_lab.backtest.report_store import PortfolioBacktestReportStore
from ashare_lab.ml.trainers.ridge import RidgeTrainer
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.portfolio.research_models import (
    PortfolioTargetBatch,
    PortfolioTargetPositionRow,
    PortfolioTargetRecord,
)
from ashare_lab.portfolio.research_store import PortfolioTargetStore
from ashare_lab.research.model_diagnostics.store import ModelDiagnosticStore
from ashare_lab.services.model_diagnostic_runtime import (
    ModelDiagnosticRuntimeError,
    run_default_model_diagnostics,
)
from ashare_lab.services.model_prediction import build_ridge_prediction_score_frame
from ashare_lab.services.portfolio_research import (
    ModelPortfolioBuildRequest,
    build_model_portfolio_targets,
)
from ashare_lab.services.training import TrainingService

from .test_portfolio_backtest_store import portfolio_report_fixture
from .training_support import build_training_evidence, folds, training_frame


def _six_symbol_training_frame() -> pl.DataFrame:
    base = training_frame()
    source = base.filter(pl.col("symbol") == "000004.SZ")
    extras = tuple(
        source.with_columns(
            pl.lit(f"00000{symbol}.SZ").alias("symbol"),
            (pl.col("factor_a") + offset).alias("factor_a"),
            (pl.col("relative_return_20d") + offset * 0.7).alias("relative_return_20d"),
            (pl.col("log_total_mv") + offset).alias("log_total_mv"),
        )
        for symbol, offset in ((5, 1.0), (6, 2.0))
    )
    return pl.concat((base, *extras)).sort("decision_time", "symbol")


def _baseline_targets(dataset_id: str, factor_id: str, trial_id: str) -> PortfolioTargetBatch:
    records = tuple(
        PortfolioTargetRecord(
            decision_date=day,
            positions=tuple(
                PortfolioTargetPositionRow(
                    symbol=f"00000{index}.SZ",
                    target_weight=0.95 / 6,
                    score=float(index),
                )
                for index in range(1, 7)
            ),
            cash_weight=0.05,
        )
        for day in (*folds()[0].test, *folds()[1].test)
    )
    return PortfolioTargetBatch(
        factor_report_id=factor_id,
        dataset_snapshot_id=dataset_id,
        trial_batch_id=trial_id,
        portfolio_rule_version="1.0.0",
        candidate_factor_names=("factor_a", "factor_b"),
        records=records,
    )


def test_model_diagnostic_runtime_reads_exact_chain_and_publishes_report(tmp_path: Path) -> None:
    # Given: one complete baseline -> Ridge -> model targets -> model backtest chain.
    artifact_root = tmp_path / "data" / "artifacts"
    frame = _six_symbol_training_frame()
    evidence, original_experiment = build_training_evidence(artifact_root, frame)
    baseline_targets = _baseline_targets(
        original_experiment.dataset_snapshot_id,
        original_experiment.factor_report_id,
        original_experiment.trial_batch_id,
    )
    baseline_target_descriptor = PortfolioTargetStore(artifact_root).write(baseline_targets)
    baseline_report = portfolio_report_fixture().model_copy(
        update={
            "target_artifact_id": baseline_target_descriptor.artifact_id,
            "factor_report_id": original_experiment.factor_report_id,
            "dataset_snapshot_id": original_experiment.dataset_snapshot_id,
        }
    )
    baseline_descriptor = PortfolioBacktestReportStore(artifact_root).write(baseline_report)
    experiment = original_experiment.model_copy(
        update={
            "portfolio_backtest_id": baseline_descriptor.report_id,
            "portfolio_rule_version": "1.0.0",
        }
    )
    trained = TrainingService(RidgeTrainer(artifact_root)).train(
        evidence,
        experiment,
        folds(),
        frame,
    )
    predictions = RidgeArtifactStore(artifact_root).read_predictions(trained.artifact)
    model_targets = build_model_portfolio_targets(
        ModelPortfolioBuildRequest(
            model_id=trained.artifact.model_id,
            factor_report_id=experiment.factor_report_id,
            dataset_snapshot_id=experiment.dataset_snapshot_id,
            trial_batch_id=experiment.trial_batch_id,
        ),
        build_ridge_prediction_score_frame(predictions),
    )
    model_target_descriptor = PortfolioTargetStore(artifact_root).write(model_targets)
    model_report = baseline_report.model_copy(
        update={
            "target_artifact_id": model_target_descriptor.artifact_id,
            "model_id": trained.artifact.model_id,
        }
    )
    model_backtest_descriptor = PortfolioBacktestReportStore(artifact_root).write(model_report)

    # When: the formal clean-artifact composition publishes the post-hoc diagnosis.
    descriptor = run_default_model_diagnostics(
        tmp_path,
        trained.artifact.model_id,
        model_backtest_descriptor.report_id,
    )

    # Then: the report fixes both backtests and cannot authorize tuning or final-test access.
    report = ModelDiagnosticStore(artifact_root).read(descriptor)
    assert report.model_id == trained.artifact.model_id
    assert report.portfolio.baseline_backtest_id == baseline_descriptor.report_id
    assert report.portfolio.model_backtest_id == model_backtest_descriptor.report_id
    assert report.tuning_permitted is False
    assert report.final_test_runs == 0


def test_model_diagnostic_runtime_translates_missing_model_to_stable_blocker(
    tmp_path: Path,
) -> None:
    # Given: an artifact root without the requested model identity.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: adapter details are translated by the formal composition boundary.
    with pytest.raises(ModelDiagnosticRuntimeError, match="model_diagnostic_runtime"):
        run_default_model_diagnostics(
            tmp_path,
            "ridge_model_" + "a" * 64,
            "portfolio_backtest_" + "b" * 64,
        )
