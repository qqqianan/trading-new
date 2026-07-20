from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.artifacts import ArtifactKind
from ashare_lab.research.datasets.spec import DatasetSpec, FeatureRef, LabelRef
from ashare_lab.research.experiments.trial_ledger import FactorTrial
from ashare_lab.research.factors.models import ExpectedDirection, FactorFamily
from ashare_lab.research.factors.runtime_frames import (
    DiagnosticFrameAssemblyError,
    DiagnosticFrameInputs,
    build_oos_diagnostic_frame,
)
from ashare_lab.research.factors.runtime_source import (
    ArtifactFactorFrameSource,
    FactorRuntimeSourceError,
)
from ashare_lab.services.factor_diagnostic_runtime import (
    FactorDiagnosticRuntimeError,
    run_default_factor_diagnostics,
)

from .training_support import LABEL, folds, training_frame


def test_diagnostic_frame_uses_only_fold_local_internal_test_rows() -> None:
    # Given: governed universe, feature, size, and label rows across two development folds.
    frame = training_frame()
    universe = frame.select("decision_time", "symbol").with_columns(
        pl.lit(value=True).alias("eligible_for_new_risk")
    )
    feature = frame.select("decision_time", "symbol", pl.col("factor_a").alias("value"))
    size = frame.select("decision_time", "symbol", pl.col("log_total_mv").alias("value"))
    label = frame.select("decision_time", "symbol", pl.col(LABEL).alias("value"))

    # When: fold preprocessing is fitted and only disjoint internal-test partitions are assembled.
    result = build_oos_diagnostic_frame(
        DiagnosticFrameInputs(universe, feature, size, label),
        folds(),
        feature_name="factor_a",
        dataset_snapshot_id="ds_abc123",
    )

    # Then: validation/train rows are absent and the diagnostic contract remains complete.
    expected_dates = (*folds()[0].test, *folds()[1].test)
    assert result.height == 16
    assert tuple(result["decision_time"].dt.date().unique().sort()) == expected_dates
    assert result.columns == [
        "decision_time",
        "symbol",
        "factor_value",
        "label_value",
        "log_total_mv",
        "industry",
        "market_regime",
    ]
    assert result["factor_value"].is_finite().all()
    assert result["industry"].null_count() == result.height


def test_size_factor_reuses_verified_size_artifact_without_duplicate_column() -> None:
    # Given: log market value is both the registered factor and neutralization size input.
    frame = training_frame()
    universe = frame.select("decision_time", "symbol").with_columns(
        pl.lit(value=True).alias("eligible_for_new_risk")
    )
    size = frame.select("decision_time", "symbol", pl.col("log_total_mv").alias("value"))
    label = frame.select("decision_time", "symbol", pl.col(LABEL).alias("value"))

    # When: the OOS frame is assembled for the size trial.
    result = build_oos_diagnostic_frame(
        DiagnosticFrameInputs(universe, size, size, label),
        folds(),
        feature_name="log_total_mv",
        dataset_snapshot_id="ds_abc123",
    )

    # Then: one standardized size value drives both diagnostic fields without alias collision.
    assert result.height == 16
    assert result["factor_value"].equals(result["log_total_mv"])


def test_diagnostic_frame_rejects_empty_walk_forward_protocol() -> None:
    # Given: complete artifact columns but no governed development fold.
    frame = training_frame()
    inputs = DiagnosticFrameInputs(
        universe=frame.select("decision_time", "symbol").with_columns(
            pl.lit(value=True).alias("eligible_for_new_risk")
        ),
        feature=frame.select("decision_time", "symbol", pl.col("factor_a").alias("value")),
        size=frame.select("decision_time", "symbol", pl.col("log_total_mv").alias("value")),
        label=frame.select("decision_time", "symbol", pl.col(LABEL).alias("value")),
    )

    # When / Then: diagnostics stop before fitting an ungoverned split.
    with pytest.raises(DiagnosticFrameAssemblyError, match="produced no folds"):
        build_oos_diagnostic_frame(
            inputs,
            (),
            feature_name="factor_a",
            dataset_snapshot_id="ds_abc123",
        )


def test_diagnostic_frame_rejects_incomplete_artifact_columns() -> None:
    # Given: a size artifact without the governed value column.
    frame = training_frame()
    inputs = DiagnosticFrameInputs(
        universe=frame.select("decision_time", "symbol").with_columns(
            pl.lit(value=True).alias("eligible_for_new_risk")
        ),
        feature=frame.select("decision_time", "symbol", pl.col("factor_a").alias("value")),
        size=frame.select("decision_time", "symbol"),
        label=frame.select("decision_time", "symbol", pl.col(LABEL).alias("value")),
    )

    # When / Then: the malformed artifact is rejected before any fold is fitted.
    with pytest.raises(DiagnosticFrameAssemblyError, match="incomplete columns"):
        build_oos_diagnostic_frame(
            inputs,
            folds(),
            feature_name="factor_a",
            dataset_snapshot_id="ds_abc123",
        )


class MemoryArtifactReader:
    """Small real DataFrame adapter implementing the verified reader contract."""

    def __init__(self, frames: dict[tuple[ArtifactKind, str], pl.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[ArtifactKind, str]] = []

    def read(self, kind: ArtifactKind, artifact_id: str) -> pl.DataFrame:
        self.calls.append((kind, artifact_id))
        return self.frames[(kind, artifact_id)]


def factor_runtime_fixture() -> tuple[
    DatasetSpec,
    FactorTrial,
    MemoryArtifactReader,
    tuple[date, ...],
]:
    timezone = ZoneInfo("Asia/Shanghai")
    dates = tuple(date(2020, 1, 1) + timedelta(days=index) for index in range(720))
    decisions = dates[::5]
    rows: list[dict[str, str | float | bool | datetime]] = [
        {
            "decision_time": datetime(
                trading_date.year,
                trading_date.month,
                trading_date.day,
                18,
                tzinfo=timezone,
            ),
            "symbol": f"00000{symbol_index + 1}.SZ",
            "eligible_for_new_risk": True,
            "factor": float(symbol_index) + date_index / 10_000,
            "size": float(10 + symbol_index),
            "label": float(symbol_index) / 100,
        }
        for date_index, trading_date in enumerate(decisions)
        for symbol_index in range(6)
    ]
    frame = pl.DataFrame(rows)
    factor_id = "feature_artifact_" + "a" * 64
    size_id = "feature_artifact_" + "b" * 64
    label_id = "label_artifact_" + "c" * 64
    universe_id = "universe_artifact_" + "d" * 64
    spec = DatasetSpec(
        rulebook_version="1.1.0",
        coverage_report_id="coverage_abc123",
        input_manifest_id="inputs_abc123",
        source_snapshot_ids=("snapshot_abc123",),
        schema_manifest_id="schema_" + "e" * 64,
        input_schema_manifest_ids=("schema_" + "f" * 64,),
        lineage_manifest_id="lineage_" + "1" * 64,
        feature_artifact_ids=(factor_id, size_id),
        feature_lineage_edge_ids=("lineage_factor", "lineage_size"),
        label_artifact_id=label_id,
        label_lineage_edge_ids=("lineage_label",),
        universe_version=universe_id,
        features=(
            FeatureRef(name="factor_a", version="1.0.0"),
            FeatureRef(name="log_total_mv", version="1.0.0"),
        ),
        label=LabelRef(name=LABEL, version="1.0.0"),
        start_date=dates[0],
        end_date=dates[-1],
    )
    trial = FactorTrial(
        trial_id="factor_trial_" + "2" * 64,
        dataset_snapshot_id=spec.snapshot_id,
        feature_name="factor_a",
        feature_version="1.0.0",
        feature_artifact_id=factor_id,
        family=FactorFamily.MOMENTUM,
        expected_direction=ExpectedDirection.HIGHER_IS_BETTER,
        simplicity_rank=0,
        diagnostic_version="1.0.0",
    )
    reader = MemoryArtifactReader(
        {
            (ArtifactKind.UNIVERSE, universe_id): frame.select(
                "decision_time", "symbol", "eligible_for_new_risk"
            ),
            (ArtifactKind.LABEL, label_id): frame.select(
                "decision_time", "symbol", pl.col("label").alias("value")
            ),
            (ArtifactKind.FEATURE, size_id): frame.select(
                "decision_time", "symbol", pl.col("size").alias("value")
            ),
            (ArtifactKind.FEATURE, factor_id): frame.select(
                "decision_time", "symbol", pl.col("factor").alias("value")
            ),
        }
    )
    return spec, trial, reader, dates


def test_artifact_factor_source_builds_verified_development_oos_frame() -> None:
    # Given: small governed artifacts spanning one complete frozen walk-forward fold.
    spec, trial, reader, calendar = factor_runtime_fixture()
    source = ArtifactFactorFrameSource(reader, spec, calendar)

    # When: the registered trial requests its frame.
    result = source.load(trial)

    # Then: shared artifacts load once and only the trial feature is loaded afterward.
    assert result.height == 78
    assert result.filter(pl.col("decision_time").dt.date() > date(2024, 12, 31)).is_empty()
    assert reader.calls[-1] == (ArtifactKind.FEATURE, trial.feature_artifact_id)


def test_artifact_factor_source_rejects_trial_artifact_substitution() -> None:
    # Given: a source bound to DatasetSpec and a trial relabeled to another artifact.
    spec, trial, reader, calendar = factor_runtime_fixture()
    source = ArtifactFactorFrameSource(reader, spec, calendar)
    altered = trial.model_copy(update={"feature_artifact_id": "feature_artifact_" + "9" * 64})

    # When / Then: no substituted feature bytes are read.
    with pytest.raises(FactorRuntimeSourceError, match="differs from DatasetSpec"):
        source.load(altered)


def test_artifact_factor_source_requires_registered_size_feature() -> None:
    # Given: a DatasetSpec whose feature registry omits the neutralization size input.
    spec, _trial, reader, calendar = factor_runtime_fixture()
    incomplete = spec.model_copy(
        update={
            "features": spec.features[:1],
            "feature_artifact_ids": spec.feature_artifact_ids[:1],
            "feature_lineage_edge_ids": spec.feature_lineage_edge_ids[:1],
        }
    )

    # When / Then: source construction fails before loading any substitute size data.
    with pytest.raises(FactorRuntimeSourceError, match="required log_total_mv"):
        ArtifactFactorFrameSource(reader, incomplete, calendar)


def test_artifact_factor_source_rejects_short_development_calendar() -> None:
    # Given: governed identities whose universe contains too little history for one fold.
    spec, _trial, reader, calendar = factor_runtime_fixture()
    universe_key = (ArtifactKind.UNIVERSE, spec.universe_version)
    short_reader = MemoryArtifactReader(
        {
            **reader.frames,
            universe_key: reader.frames[universe_key].head(60),
        }
    )

    # When / Then: the frozen walk-forward protocol cannot silently change shape.
    with pytest.raises(FactorRuntimeSourceError, match="cannot form"):
        ArtifactFactorFrameSource(short_reader, spec, calendar[:60])


def test_factor_diagnostic_runtime_requires_one_dataset_spec(tmp_path: Path) -> None:
    # Given: an artifact root without a persisted DatasetSpec.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: the composition root reports a stable identity blocker.
    with pytest.raises(FactorDiagnosticRuntimeError, match="one DatasetSpec, found 0"):
        run_default_factor_diagnostics(tmp_path)
