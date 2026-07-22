import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.ml.trainers.ridge_models import RidgeExperimentArtifact, RidgeFoldResult
from ashare_lab.portfolio.research_models import (
    PortfolioTargetBatch,
    PortfolioTargetPositionRow,
    PortfolioTargetRecord,
)
from ashare_lab.research.experiments.manifest import LabelTransform, ModelFamily
from ashare_lab.research.model_diagnostics.calculations import (
    ModelDiagnosticError,
    ModelDiagnosticInput,
    diagnose_ridge_model,
)
from ashare_lab.research.model_diagnostics.models import (
    BacktestComparison,
    CoefficientStability,
    ModelDiagnosticReport,
    RankIcSegment,
)
from ashare_lab.research.model_diagnostics.portfolio import PortfolioDiagnosticError
from ashare_lab.research.model_diagnostics.store import (
    ModelDiagnosticDescriptor,
    ModelDiagnosticStore,
    ModelDiagnosticStoreError,
)

from .test_portfolio_backtest_store import portfolio_report_fixture

ROOT = Path(__file__).parents[1]
MODEL_ID = "ridge_model_" + "a" * 64
FACTOR_ID = "factor_report_" + "b" * 64
BASELINE_ID = "portfolio_backtest_" + "c" * 64
MODEL_BACKTEST_ID = "portfolio_backtest_" + "d" * 64


def _predictions() -> pl.DataFrame:
    start = date(2023, 1, 2)
    timezone = ZoneInfo("Asia/Shanghai")
    rows = tuple(
        (
            datetime.combine(start + timedelta(days=day), datetime.min.time(), timezone),
            f"{symbol:06d}.SZ",
            day // 2,
            float(symbol),
            float(symbol),
        )
        for day in range(4)
        for symbol in range(1, 7)
    )
    return pl.DataFrame(
        rows,
        schema=("decision_time", "symbol", "fold_index", "model_score", "label_value"),
        orient="row",
    ).with_columns(pl.col("decision_time").cast(pl.Datetime("us", "Asia/Shanghai")))


def _model() -> RidgeExperimentArtifact:
    folds = tuple(
        RidgeFoldResult(
            fold_index=index,
            baseline_validation_mse=0.1,
            selected_validation_mse=0.01,
            internal_test_mse=0.0,
            internal_test_rows=12,
            coefficients=((1.0, 0.5) if index == 0 else (0.8, -0.2)),
            intercept=0.0,
        )
        for index in range(2)
    )
    return RidgeExperimentArtifact.model_construct(
        model_id=MODEL_ID,
        training_run_id="ridge_run_test",
        dataset_snapshot_id="ds_abc123",
        prediction_artifact_sha256="e" * 64,
        factor_report_id=FACTOR_ID,
        selected_alpha=100.0,
        prediction_row_count=24,
        fold_results=folds,
        model_feature_names=("factor_a", "factor_b"),
        source_portfolio_backtest_id=BASELINE_ID,
        portfolio_rule_version="1.0.0",
        model_status="DRAFT",
        final_test_runs=0,
    )


def _targets(*, model: bool) -> PortfolioTargetBatch:
    start = date(2023, 1, 2)
    first_symbol = 15 if model else 0
    records = tuple(
        PortfolioTargetRecord(
            decision_date=start + timedelta(days=day),
            positions=tuple(
                PortfolioTargetPositionRow(
                    symbol=f"{symbol:06d}.SZ",
                    target_weight=0.95 / 30,
                    score=float(symbol),
                )
                for symbol in range(first_symbol, first_symbol + 30)
            ),
            cash_weight=0.05,
        )
        for day in range(4)
    )
    return PortfolioTargetBatch(
        factor_report_id=FACTOR_ID,
        model_id=MODEL_ID if model else None,
        dataset_snapshot_id="ds_abc123",
        trial_batch_id="trial_batch_" + "f" * 64,
        portfolio_rule_version="2.0.0" if model else "1.0.0",
        candidate_factor_names=("model_prediction",) if model else ("factor_a",),
        records=records,
    )


def _input() -> ModelDiagnosticInput:
    baseline = portfolio_report_fixture().model_copy(
        update={
            "factor_report_id": FACTOR_ID,
            "target_artifact_id": "portfolio_targets_" + "1" * 64,
        }
    )
    model = baseline.model_copy(
        update={"model_id": MODEL_ID, "target_artifact_id": "portfolio_targets_" + "2" * 64}
    )
    return ModelDiagnosticInput(
        model=_model(),
        predictions=_predictions(),
        baseline_targets=_targets(model=False),
        model_targets=_targets(model=True),
        baseline_backtest_id=BASELINE_ID,
        baseline_backtest=baseline,
        model_backtest_id=MODEL_BACKTEST_ID,
        model_backtest=model,
    )


def test_model_diagnostic_discloses_rank_stability_and_like_for_like_portfolio() -> None:
    # Given: keyed predictions, every fold coefficient, and governed baseline/model ledgers.
    request = _input()

    # When: the immutable post-hoc diagnosis is calculated.
    report = diagnose_ridge_model(request)

    # Then: ranking, stability, overlap, and non-tuning scope are all explicit.
    assert report.overall_rank_ic.mean_rank_ic == 1.0
    assert tuple(item.segment for item in report.fold_segments) == ("0", "1")
    assert report.coefficient_stability[1].sign_consistency == 0.5
    assert report.portfolio.mean_top30_overlap == 0.5
    assert report.diagnostic_scope == "POST_HOC_DEVELOPMENT_ONLY"
    assert report.tuning_permitted is False
    assert report.final_test_runs == 0


def test_model_diagnostic_verifies_rank_loss_while_retaining_raw_return_labels() -> None:
    # Given: a rank Ridge whose fold loss uses rank targets but predictions retain raw returns.
    request = _input()
    rank_loss = sum((float(symbol) - (symbol - 1) / 5) ** 2 for symbol in range(1, 7)) / 6
    rank_folds = tuple(
        item.model_copy(update={"internal_test_mse": rank_loss})
        for item in request.model.fold_results
    )
    rank_model = request.model.model_copy(
        update={
            "model_family": ModelFamily.RIDGE_RANK,
            "label_transform": LabelTransform.CROSS_SECTIONAL_PERCENTILE_RANK,
            "experiment_protocol_id": "model_protocol_" + "f" * 64,
            "fold_results": rank_folds,
        }
    )

    # When: diagnostics verify the immutable rank model and raw-return prediction artifact.
    report = diagnose_ridge_model(replace(request, model=rank_model))

    # Then: objective loss integrity is checked without discarding raw-return Rank IC labels.
    assert report.overall_rank_ic.mean_rank_ic == 1.0


def test_model_diagnostic_rejects_final_holdout_rows() -> None:
    # Given: otherwise valid predictions relabeled into the sealed 2025 period.
    request = _input()
    leaked = request.predictions.with_columns(
        pl.col("decision_time").dt.offset_by("2y").alias("decision_time")
    )

    # When / Then: post-hoc diagnostics cannot become a holdout reader.
    with pytest.raises(ModelDiagnosticError, match="final holdout"):
        diagnose_ridge_model(replace(request, predictions=leaked))


def test_model_diagnostic_rejects_legacy_model_without_fold_coefficients() -> None:
    # Given: a readable legacy model whose fold evidence predates coefficient snapshots.
    request = _input()
    legacy_folds = tuple(
        item.model_copy(update={"coefficients": ()}) for item in request.model.fold_results
    )
    legacy = request.model.model_copy(update={"fold_results": legacy_folds})

    # When / Then: coefficient stability is never guessed from the final fold model.
    with pytest.raises(ModelDiagnosticError, match="coefficient evidence"):
        diagnose_ridge_model(replace(request, model=legacy))


def test_model_diagnostic_rejects_model_without_factor_lineage() -> None:
    # Given: a readable model whose original factor report identity is absent.
    request = _input()
    legacy = request.model.model_copy(update={"factor_report_id": None})

    # When / Then: the report cannot detach model behavior from factor selection evidence.
    with pytest.raises(ModelDiagnosticError, match="factor report lineage"):
        diagnose_ridge_model(replace(request, model=legacy))


def test_model_diagnostic_treats_consistently_zero_coefficient_as_stable() -> None:
    # Given: one missingness feature whose coefficient is exactly zero in every fold.
    request = _input()
    folds_with_zero = tuple(
        item.model_copy(update={"coefficients": (*item.coefficients, 0.0)})
        for item in request.model.fold_results
    )
    model = request.model.model_copy(
        update={
            "fold_results": folds_with_zero,
            "model_feature_names": (*request.model.model_feature_names, "always_present_missing"),
        }
    )

    # When: coefficient stability is summarized across folds.
    report = diagnose_ridge_model(replace(request, model=model))

    # Then: a stable zero state is not mislabeled as sign instability.
    assert report.coefficient_stability[-1].sign_consistency == 1.0


def test_model_diagnostic_rejects_noncomparable_target_dates() -> None:
    # Given: model targets silently omit one baseline decision date.
    request = _input()
    shortened = request.model_targets.model_copy(
        update={"records": request.model_targets.records[:-1]}
    )

    # When / Then: overlap is not calculated on a favorable inner intersection.
    with pytest.raises(PortfolioDiagnosticError, match="target dates differ"):
        diagnose_ridge_model(replace(request, model_targets=shortened))


def test_model_diagnostic_store_is_content_addressed_and_detects_tampering(tmp_path: Path) -> None:
    # Given: one complete post-hoc report published twice.
    report = diagnose_ridge_model(_input())
    store = ModelDiagnosticStore(tmp_path)

    # When: identical evidence is published repeatedly.
    descriptors = (store.write(report), store.write(report))

    # Then: identity is stable and modified bytes cannot retain it.
    assert descriptors[0] == descriptors[1]
    descriptors[0].report_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModelDiagnosticStoreError, match="missing or invalid"):
        store.read(descriptors[0])


def test_model_diagnostic_store_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: a valid report descriptor relabeled to an arbitrary path.
    store = ModelDiagnosticStore(tmp_path)
    descriptor = store.write(diagnose_ridge_model(_input()))
    crossed = descriptor.model_copy(update={"report_path": tmp_path / "other.json"})

    # When / Then: model evidence cannot be read outside its content directory.
    with pytest.raises(ModelDiagnosticStoreError, match="crosses"):
        store.read(crossed)


def test_model_diagnostic_store_rejects_false_digest(tmp_path: Path) -> None:
    # Given: valid report bytes paired with a false digest.
    store = ModelDiagnosticStore(tmp_path)
    descriptor = store.write(diagnose_ridge_model(_input()))
    mismatched = ModelDiagnosticDescriptor(
        report_id=descriptor.report_id,
        report_path=descriptor.report_path,
        data_sha256="f" * 64,
    )

    # When / Then: content identity is recomputed instead of trusting the caller.
    with pytest.raises(ModelDiagnosticStoreError, match="bytes differ"):
        store.read(mismatched)


def test_model_diagnostic_schema_documents_every_report_field() -> None:
    # Given: the committed machine schema for post-hoc diagnostics.
    document = json.loads(
        (ROOT / "schemas" / "model_diagnostic_report_v1.json").read_text(encoding="utf-8")
    )

    # When: required fields are compared with each Pydantic trust boundary.
    required = (
        set(document["required"]),
        set(document["$defs"]["RankIcSegment"]["required"]),
        set(document["$defs"]["CoefficientStability"]["required"]),
        set(document["$defs"]["BacktestComparison"]["required"]),
    )

    # Then: no persisted diagnostic field remains undocumented.
    assert required == (
        set(ModelDiagnosticReport.model_fields),
        set(RankIcSegment.model_fields),
        set(CoefficientStability.model_fields),
        set(BacktestComparison.model_fields),
    )
