from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.datasets.spec import DatasetSpec, FeatureRef, LabelRef
from ashare_lab.research.datasets.spec_store import DatasetSpecStore
from ashare_lab.research.experiments.trial_ledger import (
    FactorTrial,
    TrialLedgerStore,
    TrialRegistrationContext,
    create_trial_batch,
)
from ashare_lab.research.factors.models import (
    ExpectedDirection,
    FactorDiagnosticReport,
    FactorFamily,
    FactorHypothesis,
    SegmentMetric,
)
from ashare_lab.research.factors.report_store import FactorReportStore
from ashare_lab.research.factors.runtime_source import ArtifactFrameReader
from ashare_lab.research.factors.selection import (
    FactorDecision,
    FactorDecisionReason,
    FactorDecisionStatus,
    FactorResearchReport,
)
from ashare_lab.services import portfolio_runtime
from ashare_lab.services.portfolio_runtime import run_default_portfolio_targets


class MemoryScoreSource:
    """One complete candidate score frame used after real identity verification."""

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame

    def load(self, _trial: FactorTrial) -> pl.DataFrame:
        return self._frame


class NullArtifactReader:
    """Typed placeholder because the patched score source owns all frame reads."""

    def read(self, kind: ArtifactKind, artifact_id: str) -> pl.DataFrame:
        message = f"composition test score source must own reads: {kind}:{artifact_id}"
        raise AssertionError(message)


def portfolio_spec() -> DatasetSpec:
    return DatasetSpec(
        rulebook_version="1.1.0",
        coverage_report_id="coverage_abc123",
        input_manifest_id="inputs_abc123",
        source_snapshot_ids=("snap_calendar",),
        schema_manifest_id="schema_" + "a" * 64,
        input_schema_manifest_ids=("schema_" + "b" * 64,),
        lineage_manifest_id="lineage_abc123",
        feature_artifact_ids=("feature_artifact_" + "c" * 64,),
        feature_lineage_edge_ids=("lineage_feature",),
        label_artifact_id="label_artifact_abc123",
        label_lineage_edge_ids=("lineage_label",),
        universe_version="universe_artifact_abc123",
        features=(FeatureRef(name="factor_a", version="1.0.0"),),
        label=LabelRef(name="label_a", version="1.0.0"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
    )


def _diagnostic(trial: FactorTrial) -> FactorDiagnosticReport:
    segment = SegmentMetric(segment="2024", observations=40, mean_rank_ic=0.01)
    return FactorDiagnosticReport(
        trial_id=trial.trial_id,
        dataset_snapshot_id=trial.dataset_snapshot_id,
        feature_name=trial.feature_name,
        expected_direction=trial.expected_direction,
        total_sample_count=40,
        valid_pair_count=40,
        missing_feature_count=0,
        missing_label_count=0,
        coverage=1.0,
        raw_mean_rank_ic=0.01,
        oriented_mean_rank_ic=0.01,
        icir=0.1,
        direction_consistency=0.6,
        p_value=0.01,
        quintile_mean_labels=(0.0, 0.01, 0.02, 0.03, 0.04),
        quintile_monotonicity=1.0,
        top_bottom_gross_return=0.04,
        average_turnover=0.1,
        top_bottom_net_return=0.039,
        factor_autocorrelation=0.5,
        size_exposure=0.01,
        yearly_segments=(segment,),
        regime_segments=(segment,),
        industry_segments=(),
        worst_year=segment,
        worst_industry=None,
    )


def test_portfolio_runtime_publishes_from_real_identity_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: real DatasetSpec, trial, report, and one label-free candidate score frame.
    artifact_root = tmp_path / "data" / "artifacts"
    spec = portfolio_spec()
    DatasetSpecStore(artifact_root).write(spec)
    context = TrialRegistrationContext(
        dataset_snapshot_id=spec.snapshot_id,
        rulebook_version="1.1.0",
        code_commit="d" * 40,
        registered_at=datetime(2026, 7, 20, 14, tzinfo=ZoneInfo("Asia/Shanghai")),
        registered_by="research_owner",
    )
    batch = create_trial_batch(
        context,
        (
            FactorHypothesis(
                feature_name="factor_a",
                feature_version="1.0.0",
                family=FactorFamily.VALUE,
                expected_direction=ExpectedDirection.HIGHER_IS_BETTER,
                simplicity_rank=0,
            ),
        ),
        spec.feature_artifact_ids,
    )
    TrialLedgerStore(artifact_root).write(batch)
    diagnostic = _diagnostic(batch.trials[0])
    report = FactorResearchReport(
        batch_id=batch.batch_id,
        dataset_snapshot_id=spec.snapshot_id,
        maximum_q=0.1,
        diagnostics=(diagnostic,),
        decisions=(
            FactorDecision(
                trial_id=batch.trials[0].trial_id,
                feature_name="factor_a",
                status=FactorDecisionStatus.CANDIDATE,
                reasons=(FactorDecisionReason.PASSES_DIAGNOSTIC_GATES,),
                p_value=0.01,
                q_value=0.01,
            ),
        ),
    )
    report_descriptor = FactorReportStore(artifact_root).write(report)
    day = date(2024, 10, 11)
    frame = pl.DataFrame(
        tuple((day, f"{index:06d}.SZ", float(index)) for index in range(40)),
        schema=("decision_time", "symbol", "factor_value"),
        orient="row",
    )

    def reader_factory(_root: Path) -> ArtifactFrameReader:
        return NullArtifactReader()

    def calendar_loader(_root: Path, _specification: DatasetSpec) -> tuple[date, ...]:
        return (day,)

    def source_factory(
        _reader: ArtifactFrameReader,
        _specification: DatasetSpec,
        _calendar: tuple[date, ...],
    ) -> MemoryScoreSource:
        return MemoryScoreSource(frame)

    monkeypatch.setattr(portfolio_runtime, "VerifiedArtifactFrameReader", reader_factory)
    monkeypatch.setattr(portfolio_runtime, "load_dataset_development_calendar", calendar_loader)
    monkeypatch.setattr(portfolio_runtime, "ArtifactFactorScoreSource", source_factory)

    # When: the real composition root publishes the explicit report's target batch.
    descriptor = run_default_portfolio_targets(tmp_path, report_descriptor.report_id)

    # Then: a content-addressed Top 30 batch is persisted without label or order fields.
    assert descriptor.artifact_id.startswith("portfolio_targets_")
    assert descriptor.artifact_path.exists()
