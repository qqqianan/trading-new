from datetime import date
from pathlib import Path
from typing import ClassVar

import polars as pl
import pytest

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
)
from ashare_lab.code_identity import GitEvidence
from ashare_lab.ml.registry import ModelStatus
from ashare_lab.ml.trainers.ridge_store import RidgeArtifactStore
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.portfolio.research_store import PortfolioTargetDescriptor, PortfolioTargetStore
from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.artifacts.models import ArtifactManifest
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.datasets.spec_store import DatasetSpecStore
from ashare_lab.research.experiments.manifest import ModelFamily
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol
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
from ashare_lab.research.splits.walk_forward import WalkForwardFold
from ashare_lab.services import training_runtime, training_runtime_support
from ashare_lab.services.training_runtime import (
    run_default_ridge_training,
    run_protocol_rank_ridge_training,
)
from ashare_lab.services.training_runtime_support import (
    TrainingRuntimeError,
    artifact_sha256,
    sole_artifact_path,
)

from .training_support import LABEL, build_training_evidence, folds, training_frame


class MemoryTrainingReader:
    """Verified-reader replacement backed by exact in-memory artifact rows."""

    frames: ClassVar[dict[tuple[ArtifactKind, str], pl.DataFrame]] = {}

    def __init__(self, _project_root: Path) -> None:
        """Match the production reader construction boundary."""

    def read(self, kind: ArtifactKind, artifact_id: str) -> pl.DataFrame:
        """Return the registered immutable test frame."""
        return self.frames[(kind, artifact_id)]


def _write_placeholder(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")


def _feature(frame: pl.DataFrame, name: str) -> pl.DataFrame:
    return frame.select(
        "symbol",
        "decision_time",
        pl.lit(name).alias("feature_id"),
        pl.lit("1.0.0").alias("feature_version"),
        pl.col(name).alias("value"),
        pl.col("decision_time").alias("available_at"),
        pl.lit("ACCEPTED").alias("quality_status"),
    )


@pytest.mark.parametrize("model_family", [ModelFamily.RIDGE, ModelFamily.RIDGE_RANK])
def test_real_training_runtime_reaches_ridge_only_through_governed_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_family: ModelFamily,
) -> None:
    # Given: one complete local research chain and verified in-memory artifact adapter.
    project_root = tmp_path
    artifact_root = project_root / "data" / "artifacts"
    frame = training_frame()
    evidence, experiment = build_training_evidence(artifact_root, frame)
    spec = DatasetSpecStore(artifact_root).read(evidence.dataset_descriptor)
    candidates = ("factor_a", "factor_b", "log_total_mv")
    decisions = tuple(
        FactorDecision(
            trial_id=f"factor_trial_{index:064x}",
            feature_name=name,
            status=FactorDecisionStatus.CANDIDATE,
            reasons=(FactorDecisionReason.PASSES_DIAGNOSTIC_GATES,),
            p_value=0.01,
            q_value=0.02,
        )
        for index, name in enumerate(candidates, start=1)
    )
    report_id = "factor_report_" + "a" * 64
    backtest_id = "portfolio_backtest_" + "b" * 64
    target_id = "portfolio_targets_" + "c" * 64
    report = FactorResearchReport.model_construct(
        batch_id=experiment.trial_batch_id,
        dataset_snapshot_id=spec.snapshot_id,
        maximum_q=0.1,
        diagnostics=(),
        decisions=decisions,
    )
    targets = PortfolioTargetBatch.model_construct(
        factor_report_id=report_id,
        dataset_snapshot_id=spec.snapshot_id,
        trial_batch_id=experiment.trial_batch_id,
        portfolio_rule_version="1.0.0",
        candidate_factor_names=candidates,
        records=(),
    )
    backtest = PortfolioBacktestReport.model_construct(
        target_artifact_id=target_id,
        factor_report_id=report_id,
        dataset_snapshot_id=spec.snapshot_id,
        cost_rule_version="china_a_cost_v1",
        risk_rule_version="portfolio_risk_v1",
        final_test_runs=0,
    )
    report_path = artifact_root / "factor_report" / report_id / "report.json"
    backtest_path = artifact_root / "portfolio_backtests" / backtest_id / "report.json"
    target_path = artifact_root / "portfolio_targets" / target_id / "targets.json"
    for path in (report_path, backtest_path, target_path):
        _write_placeholder(path)
    universe = frame.select("symbol", "decision_time").with_columns(
        pl.col("decision_time").alias("available_at"),
        pl.lit(value=True).alias("eligible_for_new_risk"),
    )
    label = frame.select(
        "symbol",
        "decision_time",
        pl.lit(LABEL).alias("label_id"),
        pl.lit("1.0.0").alias("label_version"),
        pl.col(LABEL).alias("value"),
    )
    feature_ids = dict(
        zip(
            (item.name for item in spec.features),
            spec.feature_artifact_ids,
            strict=True,
        )
    )
    MemoryTrainingReader.frames = {
        (ArtifactKind.UNIVERSE, spec.universe_version): universe,
        (ArtifactKind.LABEL, spec.label_artifact_id): label,
        **{(ArtifactKind.FEATURE, feature_ids[name]): _feature(frame, name) for name in candidates},
    }

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

    def read_targets(
        _store: PortfolioTargetStore,
        _descriptor: PortfolioTargetDescriptor,
    ) -> PortfolioTargetBatch:
        return targets

    def manifest(_path: Path) -> ArtifactManifest:
        return ArtifactManifest.model_construct(schema_manifest_id="schema_" + "d" * 64)

    def calendar(_root: Path, _spec: DatasetSpec) -> tuple[date, ...]:
        return ()

    def development_folds(_dates: tuple[date, ...]) -> tuple[WalkForwardFold, ...]:
        return folds()

    def git_evidence(_root: Path) -> GitEvidence:
        return GitEvidence(commit="e" * 40, is_clean=True)

    monkeypatch.setattr(FactorReportStore, "read", read_report)
    monkeypatch.setattr(PortfolioBacktestReportStore, "read", read_backtest)
    monkeypatch.setattr(PortfolioTargetStore, "read", read_targets)
    monkeypatch.setattr(training_runtime, "VerifiedArtifactFrameReader", MemoryTrainingReader)
    monkeypatch.setattr(training_runtime_support, "load_manifest", manifest)
    monkeypatch.setattr(training_runtime, "load_dataset_development_calendar", calendar)
    monkeypatch.setattr(training_runtime, "build_development_folds", development_folds)
    monkeypatch.setattr(training_runtime, "load_git_evidence", git_evidence)

    protocol = ModelExperimentProtocol.model_construct(
        protocol_id="model_protocol_" + "f" * 64,
        dataset_snapshot_id=spec.snapshot_id,
        schema_manifest_id=spec.schema_manifest_id,
        lineage_manifest_id=spec.lineage_manifest_id,
        feature_names=candidates,
        label_name=spec.label.name,
        portfolio_rule_version="2.0.0",
        cost_rule_version="china_a_cost_v1",
        risk_rule_version="portfolio_risk_v1",
    )

    # When: the formal real-data composition root trains the declared Ridge objective.
    result = (
        run_protocol_rank_ridge_training(project_root, report_id, backtest_id, protocol)
        if model_family is ModelFamily.RIDGE_RANK
        else run_default_ridge_training(project_root, report_id, backtest_id)
    )

    # Then: source portfolio lineage stays 1.0.0 and final holdout remains untouched.
    assert result.artifact.model_id.startswith("ridge_model_")
    assert result.record.status is ModelStatus.DRAFT
    assert RidgeArtifactStore(artifact_root).read(result.artifact).portfolio_rule_version == "1.0.0"
    assert not (project_root / "data" / "governance" / "final_holdout_access").exists()


def test_training_runtime_support_rejects_ambiguous_dataset_paths(tmp_path: Path) -> None:
    # Given: no content-addressed DatasetSpec under the expected root.
    root = tmp_path / "dataset_spec"

    # When / Then: runtime assembly cannot guess which dataset to train.
    with pytest.raises(TrainingRuntimeError, match="exactly one DatasetSpec"):
        sole_artifact_path(root, "ds_*/manifest.json")


def test_training_runtime_support_translates_missing_artifact(tmp_path: Path) -> None:
    # Given: a descriptor path whose artifact bytes do not exist.
    missing = tmp_path / "missing.json"

    # When / Then: hashing fails through the stable training runtime boundary.
    with pytest.raises(TrainingRuntimeError, match="artifact cannot be read"):
        artifact_sha256(missing)
