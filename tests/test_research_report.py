from datetime import date
from pathlib import Path

import pytest

from ashare_lab.research.workflow_models import (
    ResearchModelStatus,
    ResearchRunRequest,
    ResearchStage,
    StageRecord,
    StageStatus,
)
from ashare_lab.research.workflow_store import ResearchReportStore, ResearchReportStoreError
from ashare_lab.services.research_workflow import ResearchWorkflowError, ResearchWorkflowService


class RecordingPipeline:
    """Return deterministic stage records while exposing execution order."""

    def __init__(self, blocked_stage: ResearchStage | None = None) -> None:
        self.calls: list[ResearchStage] = []
        self._blocked_stage = blocked_stage

    def execute(self, stage: ResearchStage, _request: ResearchRunRequest) -> StageRecord:
        self.calls.append(stage)
        status = StageStatus.BLOCKED if stage is self._blocked_stage else StageStatus.COMPLETED
        failures = (
            ("quality_gate: missing accepted evidence",) if status is StageStatus.BLOCKED else ()
        )
        return StageRecord(
            stage=stage,
            status=status,
            artifact_ids=(f"{stage.value}_artifact",) if status is StageStatus.COMPLETED else (),
            failures=failures,
        )


class WrongStagePipeline:
    """Return a forged stage identity from the first adapter call."""

    def execute(self, stage: ResearchStage, _request: ResearchRunRequest) -> StageRecord:
        forged = ResearchStage.TRAIN if stage is ResearchStage.QUALIFY else ResearchStage.QUALIFY
        return StageRecord(
            stage=forged,
            status=StageStatus.COMPLETED,
        )


def request() -> ResearchRunRequest:
    return ResearchRunRequest(
        data_cutoff=date(2024, 12, 31),
        dataset_snapshot_id="ds_abc123",
        schema_manifest_id="schema_" + "a" * 64,
        lineage_manifest_id="lineage_" + "b" * 64,
        git_commit="e" * 40,
        uv_lock_sha256="f" * 64,
        rulebook_version="1.1.0",
        database_name="ashare_quant",
        universe_rule_version="medium_horizon_universe_v1",
        factor_formulas=("mom_20=close/close_lag_20-1", "roe=profit/equity"),
        trial_ids=("factor_trial_" + "c" * 64, "factor_trial_" + "d" * 64),
        cost_rule_version="china_a_cost_v1",
        risk_rule_version="portfolio_risk_v1",
        worst_period="2022: pending real backtest",
        model_status=ResearchModelStatus.DRAFT,
        final_test_runs=0,
    )


def test_workflow_executes_all_stages_in_constitutional_order() -> None:
    # Given: a deterministic pipeline and a development-only request.
    pipeline = RecordingPipeline()

    # When: the one-click workflow runs.
    report = ResearchWorkflowService(pipeline).run(request())

    # Then: no stage can be reordered or omitted before the DRAFT report is issued.
    assert tuple(pipeline.calls) == tuple(ResearchStage)
    assert tuple(item.stage for item in report.stages) == tuple(ResearchStage)
    assert report.status is StageStatus.COMPLETED
    assert report.final_test_runs == 0


def test_workflow_stops_after_first_blocked_stage() -> None:
    # Given: materialization is blocked by governed evidence.
    pipeline = RecordingPipeline(ResearchStage.MATERIALIZE)

    # When: the workflow attempts the fixed stage sequence.
    report = ResearchWorkflowService(pipeline).run(request())

    # Then: downstream diagnostics, portfolio, backtest, and training never execute.
    assert pipeline.calls == [ResearchStage.QUALIFY, ResearchStage.MATERIALIZE]
    assert report.status is StageStatus.BLOCKED
    assert report.failures == ("quality_gate: missing accepted evidence",)


def test_report_store_is_deterministic_and_writes_complete_chinese_report(
    tmp_path: Path,
) -> None:
    # Given: one completed report with the full required disclosure context.
    report = ResearchWorkflowService(RecordingPipeline()).run(request())
    store = ResearchReportStore(tmp_path)

    # When: identical reports are published twice.
    first = store.write(report)
    second = store.write(report)

    # Then: identity is stable and the Chinese report discloses every governed boundary.
    markdown = first.markdown_path.read_text(encoding="utf-8")
    assert second == first
    assert report.report_id == first.report_id
    assert "2024-12-31" in markdown
    assert report.dataset_snapshot_id in markdown
    assert report.schema_manifest_id in markdown
    assert report.lineage_manifest_id in markdown
    assert "mom_20=close/close_lag_20-1" in markdown
    assert "china_a_cost_v1" in markdown
    assert "portfolio_risk_v1" in markdown
    assert "最差区间" in markdown
    assert "DRAFT" in markdown
    assert "不构成投资建议" in markdown


def test_workflow_rejects_stage_identity_substitution() -> None:
    # Given: an adapter that claims training while qualification is executing.
    service = ResearchWorkflowService(WrongStagePipeline())

    # When / Then: stage substitution cannot reorder or skip the workflow.
    with pytest.raises(ResearchWorkflowError, match="while executing qualify"):
        service.run(request())


def test_report_store_rejects_independently_edited_markdown(tmp_path: Path) -> None:
    # Given: a published bilingual report whose Markdown is edited independently.
    store = ResearchReportStore(tmp_path)
    descriptor = store.write(ResearchWorkflowService(RecordingPipeline()).run(request()))
    descriptor.markdown_path.write_text("替换后的结论\n", encoding="utf-8")

    # When / Then: human-readable output cannot diverge from the machine fact.
    with pytest.raises(ResearchReportStoreError, match="differs"):
        store.read(descriptor)
