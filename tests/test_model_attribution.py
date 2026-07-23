import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from ashare_lab.domain.market import Symbol
from ashare_lab.domain.risk import RiskAction, RiskEvent, RiskRule
from ashare_lab.portfolio.research_models import PortfolioTargetPositionRow
from ashare_lab.research.model_attribution.calculations import (
    ModelAttributionError,
    ModelAttributionInput,
    attribute_model_portfolio,
)
from ashare_lab.research.model_attribution.models import (
    AnnualPerformanceAttribution,
    ExecutionConstraintAttribution,
    ModelPerformanceAttributionReport,
    TailReturnAttribution,
)
from ashare_lab.research.model_attribution.portfolio import (
    PortfolioAttributionError,
    annual_performance,
    risk_constraints,
)
from ashare_lab.research.model_attribution.store import (
    ModelAttributionStore,
    ModelAttributionStoreError,
)

from .test_model_diagnostics import (
    BASELINE_ID,
    MODEL_BACKTEST_ID,
    model_diagnostic_input_fixture,
)

ROOT = Path(__file__).parents[1]
DIAGNOSTIC_ID = "model_diagnostic_" + "9" * 64


def _request() -> ModelAttributionInput:
    source = model_diagnostic_input_fixture()
    aligned_records = tuple(
        record.model_copy(
            update={
                "positions": tuple(
                    PortfolioTargetPositionRow(
                        symbol=f"{symbol:06d}.SZ",
                        target_weight=0.95 / 3,
                        score=float(symbol),
                    )
                    for symbol in range(4, 7)
                )
            }
        )
        for record in source.model_targets.records
    )
    model_targets = source.model_targets.model_copy(update={"records": aligned_records})
    baseline = source.baseline_backtest.model_copy(
        update={"metrics": replace(source.baseline_backtest.metrics, pending_order_count=2)}
    )
    model = source.model_backtest.model_copy(
        update={"metrics": replace(source.model_backtest.metrics, pending_order_count=5)}
    )
    return ModelAttributionInput(
        diagnostic_report_id=DIAGNOSTIC_ID,
        model=source.model,
        predictions=source.predictions,
        model_targets=model_targets,
        baseline_backtest_id=BASELINE_ID,
        baseline_backtest=baseline,
        model_backtest_id=MODEL_BACKTEST_ID,
        model_backtest=model,
    )


def test_attribution_uses_exact_selected_keys_and_raw_forward_returns() -> None:
    # Given: model targets select the upper half of each keyed development cross-section.
    request = _request()

    # When: the frozen portfolio attribution is calculated.
    report = attribute_model_portfolio(request)

    # Then: selected-tail lift is measured from raw labels without fitting or execution claims.
    assert report.overall_tail.mean_selected_label_return == 5.0
    assert report.overall_tail.mean_universe_label_return == 3.5
    assert report.overall_tail.mean_bottom_label_return == 2.0
    assert report.overall_tail.selected_excess_vs_universe == 1.5
    assert report.overall_tail.selected_minus_bottom == 3.0
    assert report.overall_tail.selected_daily_win_rate == 1.0
    assert report.label_semantics == "raw_forward_return_for_diagnostics"
    assert report.tail_selection_scope == "LABEL_COMPLETE_PREDICTION_UNIVERSE_TOP_N"
    assert report.tuning_permitted is False
    assert report.final_test_runs == 0


def test_attribution_discloses_annual_performance_and_execution_constraints() -> None:
    # Given: comparable governed backtests with explicit annual and risk evidence.
    request = _request()

    # When: portfolio outcomes are attributed.
    report = attribute_model_portfolio(request)

    # Then: like-for-like annual gaps and pending execution evidence remain visible.
    assert report.annual_performance[0].return_gap == 0.0
    assert report.baseline_pending_orders == 2
    assert report.model_pending_orders == 5
    assert report.model_risk_event_count == len(request.model_backtest.result.risk_events)


def test_execution_attribution_groups_repeated_risk_events() -> None:
    # Given: two identical governed resize events for one symbol.
    report = _request().model_backtest
    event = RiskEvent(
        trading_date=date(2024, 1, 2),
        rule=RiskRule.VOLUME_PARTICIPATION,
        action=RiskAction.RESIZE,
        observed=0.2,
        limit=0.1,
        message="capacity constrained",
        symbol=Symbol("000001.SZ"),
    )
    result = replace(report.result, risk_events=(event, event))

    # When: execution constraints are grouped for disclosure.
    constraints = risk_constraints("MODEL", report.model_copy(update={"result": result}))

    # Then: repeated events remain counted while affected symbols are deduplicated.
    assert constraints[0].event_count == 2
    assert constraints[0].affected_symbols == 1


def test_annual_attribution_rejects_mismatched_benchmark() -> None:
    # Given: compared reports claim different benchmark returns for the same year.
    request = _request()
    segment = request.model_backtest.metrics.annual_segments[0]
    altered_segment = replace(segment, benchmark_return=segment.benchmark_return + 0.01)
    metrics = replace(request.model_backtest.metrics, annual_segments=(altered_segment,))
    altered = request.model_backtest.model_copy(update={"metrics": metrics})

    # When / Then: annual gaps cannot be published across benchmark bases.
    with pytest.raises(PortfolioAttributionError, match="benchmarks differ"):
        annual_performance(request.baseline_backtest, altered)


def test_annual_attribution_rejects_absent_segments() -> None:
    # Given: one compared backtest omits annual performance evidence.
    request = _request()
    metrics = replace(request.model_backtest.metrics, annual_segments=())
    altered = request.model_backtest.model_copy(update={"metrics": metrics})

    # When / Then: attribution does not infer annual results from other artifacts.
    with pytest.raises(PortfolioAttributionError, match="years differ"):
        annual_performance(request.baseline_backtest, altered)


def test_attribution_rejects_final_holdout_predictions() -> None:
    # Given: prediction timestamps have been moved into the sealed final holdout.
    request = _request()
    leaked = request.predictions.with_columns(
        pl.col("decision_time").dt.offset_by("2y").alias("decision_time")
    )

    # When / Then: an attribution reader cannot become a second holdout path.
    with pytest.raises(ModelAttributionError, match="final holdout"):
        attribute_model_portfolio(replace(request, predictions=leaked))


def test_attribution_tail_scope_does_not_treat_actual_targets_as_label_complete() -> None:
    # Given: one actual target has no row in the finite-label prediction universe.
    request = _request()
    first = request.model_targets.records[0]
    altered_position = first.positions[0].model_copy(update={"symbol": "999999.SZ"})
    altered_record = first.model_copy(
        update={"positions": (altered_position, *first.positions[1:])}
    )
    altered_targets = request.model_targets.model_copy(
        update={"records": (altered_record, *request.model_targets.records[1:])}
    )

    # When: tail diagnostics rank the registered TopN count only within prediction evidence.
    report = attribute_model_portfolio(replace(request, model_targets=altered_targets))

    # Then: label-complete diagnostics remain separate from actual portfolio outcomes.
    assert report.overall_tail.mean_selected_label_return == 5.0
    assert report.tail_selection_scope == "LABEL_COMPLETE_PREDICTION_UNIVERSE_TOP_N"


def test_attribution_rejects_topn_larger_than_label_complete_universe() -> None:
    # Given: a registered target count larger than one day's prediction universe.
    request = _request()
    first = request.model_targets.records[0]
    oversized = first.model_copy(
        update={"positions": (*first.positions, *first.positions, first.positions[0])}
    )
    altered = request.model_targets.model_copy(
        update={"records": (oversized, *request.model_targets.records[1:])}
    )

    # When / Then: attribution cannot shrink TopN or duplicate finite-label observations.
    with pytest.raises(ModelAttributionError, match="exceeds finite-label"):
        attribute_model_portfolio(replace(request, model_targets=altered))


def test_attribution_store_is_content_addressed_and_detects_tampering(tmp_path: Path) -> None:
    # Given: one complete attribution report published twice.
    report = attribute_model_portfolio(_request())
    store = ModelAttributionStore(tmp_path)

    # When: identical evidence is written repeatedly.
    descriptors = (store.write(report), store.write(report))

    # Then: identity is stable and modified bytes cannot retain it.
    assert descriptors[0] == descriptors[1]
    descriptors[0].report_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModelAttributionStoreError, match="missing or invalid"):
        store.read(descriptors[0])


def test_attribution_schema_documents_every_report_field() -> None:
    # Given: the committed machine schema for post-hoc portfolio attribution.
    document = json.loads(
        (ROOT / "schemas" / "model_performance_attribution_v1.json").read_text(encoding="utf-8")
    )

    # When: required fields are compared with every persisted trust boundary.
    required = (
        set(document["required"]),
        set(document["$defs"]["TailReturnAttribution"]["required"]),
        set(document["$defs"]["AnnualPerformanceAttribution"]["required"]),
        set(document["$defs"]["ExecutionConstraintAttribution"]["required"]),
    )

    # Then: no attribution field remains undocumented.
    assert required == (
        set(ModelPerformanceAttributionReport.model_fields),
        set(TailReturnAttribution.model_fields),
        set(AnnualPerformanceAttribution.model_fields),
        set(ExecutionConstraintAttribution.model_fields),
    )
