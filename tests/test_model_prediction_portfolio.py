from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
)
from ashare_lab.ml.trainers.ridge import RidgeTrainer
from ashare_lab.ml.trainers.ridge_models import (
    FoldPredictionBatch,
    RidgePredictionArtifact,
)
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.portfolio.research_store import PortfolioTargetStore
from ashare_lab.research.factors.report_store import (
    FactorReportDescriptor,
    FactorReportStore,
)
from ashare_lab.research.factors.selection import (
    FactorDecision,
    FactorDecisionReason,
    FactorDecisionStatus,
    FactorResearchReport,
)
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256
from ashare_lab.services.model_portfolio_runtime import (
    ModelPortfolioRuntimeError,
    run_default_model_portfolio,
)
from ashare_lab.services.model_prediction import (
    RidgePredictionFrameError,
    build_ridge_prediction_score_frame,
)
from ashare_lab.services.portfolio_research import (
    ModelPortfolioBuildRequest,
    PortfolioResearchError,
    build_model_portfolio_targets,
)
from ashare_lab.services.training import TrainingService

from .training_support import build_training_evidence, folds, training_frame


def test_ridge_prediction_frame_exposes_keys_and_scores_without_labels(tmp_path: Path) -> None:
    # Given: one governed Ridge artifact containing internal-test predictions.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    result = TrainingService(RidgeTrainer(tmp_path)).train(
        evidence,
        experiment,
        folds(),
        frame,
    )
    predictions = RidgeArtifactStore(tmp_path).read_predictions(result.artifact)

    # When: the model output crosses into the portfolio-facing score boundary.
    scores = build_ridge_prediction_score_frame(predictions)

    # Then: exact observation keys and scores are available without target labels.
    assert scores.columns == ["decision_time", "symbol", "model_score"]
    assert scores.height == sum(len(batch.predictions) for batch in predictions.batches)
    assert not scores.select("decision_time", "symbol").is_duplicated().any()


def test_legacy_hash_only_predictions_cannot_enter_portfolio() -> None:
    # Given: a legacy prediction artifact that retained only the observation-key hash.
    predictions = RidgePredictionArtifact(
        dataset_snapshot_id="ds_abc123",
        training_run_id="ridge_run_legacy",
        batches=(
            FoldPredictionBatch(
                fold_index=0,
                observation_keys_sha256="a" * 64,
                predictions=(0.1,),
                labels=(0.2,),
            ),
        ),
    )

    # When / Then: row order is never guessed from another artifact.
    with pytest.raises(RidgePredictionFrameError, match="observation keys are absent"):
        build_ridge_prediction_score_frame(predictions)


def test_model_scores_build_a_model_identified_top30_target_batch(tmp_path: Path) -> None:
    # Given: governed keyed Ridge predictions and their explicit research identities.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    result = TrainingService(RidgeTrainer(tmp_path)).train(
        evidence,
        experiment,
        folds(),
        frame,
    )
    predictions = RidgeArtifactStore(tmp_path).read_predictions(result.artifact)
    scores = build_ridge_prediction_score_frame(predictions)
    request = ModelPortfolioBuildRequest(
        model_id=result.artifact.model_id,
        factor_report_id=experiment.factor_report_id,
        dataset_snapshot_id=experiment.dataset_snapshot_id,
        trial_batch_id=experiment.trial_batch_id,
    )

    # When: model predictions pass through the shared Top-N portfolio builder.
    targets = build_model_portfolio_targets(request, scores)

    # Then: targets retain model lineage and still have no order capability.
    assert targets.model_id == result.artifact.model_id
    assert targets.candidate_factor_names == ("model_prediction",)
    assert all(len(record.positions) <= 30 for record in targets.records)
    assert not hasattr(targets.records[0], "orders")


def test_model_portfolio_runtime_verifies_research_chain_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a keyed Ridge model plus matching immutable report and source backtest identities.
    artifact_root = tmp_path / "data" / "artifacts"
    frame = training_frame()
    evidence, experiment = build_training_evidence(artifact_root, frame)
    result = TrainingService(RidgeTrainer(artifact_root)).train(
        evidence,
        experiment,
        folds(),
        frame,
    )
    decisions = tuple(
        FactorDecision(
            trial_id=f"factor_trial_{index:064x}",
            feature_name=name,
            status=FactorDecisionStatus.CANDIDATE,
            reasons=(FactorDecisionReason.PASSES_DIAGNOSTIC_GATES,),
            p_value=0.01,
            q_value=0.02,
        )
        for index, name in enumerate(experiment.feature_names, start=1)
    )
    report = FactorResearchReport.model_construct(
        batch_id=experiment.trial_batch_id,
        dataset_snapshot_id=experiment.dataset_snapshot_id,
        maximum_q=0.1,
        diagnostics=(),
        decisions=decisions,
    )
    backtest = PortfolioBacktestReport.model_construct(
        factor_report_id=experiment.factor_report_id,
        dataset_snapshot_id=experiment.dataset_snapshot_id,
        cost_rule_version=experiment.cost_rule_version,
        final_test_runs=0,
    )
    report_path = artifact_root / "factor_report" / experiment.factor_report_id / "report.json"
    backtest_path = (
        artifact_root / "portfolio_backtests" / experiment.portfolio_backtest_id / "report.json"
    )
    for path in (report_path, backtest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    def read_report(
        _store: FactorReportStore,
        _descriptor: FactorReportDescriptor,
    ) -> FactorResearchReport:
        return report

    def read_backtest(
        _store: PortfolioBacktestReportStore,
        _descriptor: PortfolioBacktestReportDescriptor,
    ) -> PortfolioBacktestReport:
        return backtest

    monkeypatch.setattr(FactorReportStore, "read", read_report)
    monkeypatch.setattr(PortfolioBacktestReportStore, "read", read_backtest)

    # When: the formal model-portfolio composition root publishes targets.
    descriptor = run_default_model_portfolio(tmp_path, result.artifact.model_id)

    # Then: stored target lineage names the exact model and remains development-only.
    targets = PortfolioTargetStore(artifact_root).read(descriptor)
    assert targets.model_id == result.artifact.model_id
    assert targets.portfolio_rule_version == "2.0.0"


def _keyed_predictions(*, key_hash: str | None = None) -> RidgePredictionArtifact:
    decision_time = datetime(2024, 1, 5, 18, tzinfo=ZoneInfo("Asia/Shanghai"))
    keys = pl.DataFrame(
        {"decision_time": [decision_time], "symbol": ["000001.SZ"]},
        schema={
            "decision_time": pl.Datetime("us", "Asia/Shanghai"),
            "symbol": pl.String,
        },
    )
    batch = FoldPredictionBatch(
        fold_index=0,
        observation_keys_sha256=key_hash or training_frame_sha256(keys),
        predictions=(0.1,),
        labels=(0.2,),
        decision_times=(decision_time,),
        symbols=("000001.SZ",),
    )
    return RidgePredictionArtifact(
        dataset_snapshot_id="ds_abc123",
        training_run_id="ridge_run_test",
        batches=(batch,),
    )


def test_ridge_prediction_frame_rejects_changed_key_hash() -> None:
    # Given: keyed prediction rows whose declared digest belongs to other observations.
    predictions = _keyed_predictions(key_hash="f" * 64)

    # When / Then: readable keys cannot bypass their immutable observation identity.
    with pytest.raises(RidgePredictionFrameError, match="key hash differs"):
        build_ridge_prediction_score_frame(predictions)


def test_ridge_prediction_frame_rejects_overlapping_fold_keys() -> None:
    # Given: two internal-test folds claiming the same observation key.
    original = _keyed_predictions()
    duplicate = original.batches[0].model_copy(update={"fold_index": 1})
    predictions = original.model_copy(update={"batches": (*original.batches, duplicate)})

    # When / Then: overlapping out-of-sample predictions fail closed.
    with pytest.raises(RidgePredictionFrameError, match="overlap"):
        build_ridge_prediction_score_frame(predictions)


def test_model_portfolio_rejects_score_frame_with_label_capability() -> None:
    # Given: a model score frame contaminated with a target column.
    scores = build_ridge_prediction_score_frame(_keyed_predictions()).with_columns(
        pl.lit(0.2).alias("label")
    )
    request = ModelPortfolioBuildRequest(
        model_id="ridge_model_" + "a" * 64,
        factor_report_id="factor_report_" + "b" * 64,
        dataset_snapshot_id="ds_abc123",
        trial_batch_id="trial_batch_" + "c" * 64,
    )

    # When / Then: portfolio construction accepts only keys and model_score.
    with pytest.raises(PortfolioResearchError, match="only exact keys"):
        build_model_portfolio_targets(request, scores)


def test_model_portfolio_rejects_duplicate_score_keys() -> None:
    # Given: the same model observation appears twice.
    scores = build_ridge_prediction_score_frame(_keyed_predictions())
    request = ModelPortfolioBuildRequest(
        model_id="ridge_model_" + "a" * 64,
        factor_report_id="factor_report_" + "b" * 64,
        dataset_snapshot_id="ds_abc123",
        trial_batch_id="trial_batch_" + "c" * 64,
    )

    # When / Then: duplicated scores cannot multiply target candidates.
    with pytest.raises(PortfolioResearchError, match="duplicated"):
        build_model_portfolio_targets(request, pl.concat((scores, scores)))


def test_model_portfolio_runtime_translates_missing_model_to_stable_blocker(
    tmp_path: Path,
) -> None:
    # Given: an artifact root without the requested Ridge identity.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: storage detail is translated at the composition boundary.
    with pytest.raises(ModelPortfolioRuntimeError, match="model_portfolio_runtime"):
        run_default_model_portfolio(tmp_path, "ridge_model_" + "a" * 64)
