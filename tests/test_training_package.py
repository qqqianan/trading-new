from dataclasses import replace
from pathlib import Path

import pytest

from ashare_lab.research.datasets.spec_store import DatasetSpecStore
from ashare_lab.research.model_evidence import TrainingLineageDocument, TrainingSchemaDocument
from ashare_lab.research.training.package import (
    TrainingColumnSource,
    TrainingPackageError,
    TrainingPackageRequest,
    build_training_package,
)

from .training_support import FEATURES, LABEL, build_training_evidence, folds, training_frame


def _request(tmp_path: Path) -> TrainingPackageRequest:
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path / "source", frame)
    spec = DatasetSpecStore(evidence.artifact_root).read(evidence.dataset_descriptor)
    schema_id = "schema_" + "a" * 64
    artifacts = {
        "decision_time": "universe_v1",
        "symbol": "universe_v1",
        "factor_a": "feature_a",
        "factor_b": "feature_b",
        "log_total_mv": "feature_size",
        LABEL: "label_a",
    }
    return TrainingPackageRequest(
        artifact_root=tmp_path / "source",
        holdout_ledger_root=tmp_path / "holdout",
        dataset_descriptor=evidence.dataset_descriptor,
        dataset_spec=spec,
        feature_names=FEATURES,
        size_feature_name="log_total_mv",
        label_name=LABEL,
        label_version="1.0.0",
        column_sources=tuple(
            TrainingColumnSource(name, artifacts[name], schema_id) for name in frame.columns
        ),
        git_commit="a" * 40,
        trial_batch_id=experiment.trial_batch_id,
        factor_report_id="factor_report_" + "b" * 64,
        portfolio_backtest_id="portfolio_backtest_" + "c" * 64,
        portfolio_rule_version="1.0.0",
        cost_rule_version="china_a_cost_v1",
    )


def test_training_package_is_deterministic_and_documents_each_physical_column_once(
    tmp_path: Path,
) -> None:
    # Given: one real-shaped DatasetSpec contract where size is also a model feature.
    request = _request(tmp_path)
    frame = training_frame()

    # When: the package is materialized twice from identical governed inputs.
    first = build_training_package(request, folds(), frame)
    second = build_training_package(request, folds(), frame)

    # Then: every identity is stable and no duplicate size lineage is invented.
    assert first == second
    schema = TrainingSchemaDocument.model_validate_json(
        first.evidence.schema_descriptor.path.read_bytes()
    )
    lineage = TrainingLineageDocument.model_validate_json(
        first.evidence.lineage_descriptor.path.read_bytes()
    )
    assert tuple(item.field_name for item in schema.fields) == tuple(frame.columns)
    assert tuple(item.field_name for item in lineage.fields) == tuple(frame.columns)
    assert tuple(item.field_name for item in lineage.fields).count("log_total_mv") == 1
    assert first.experiment.final_test_runs == 0


def test_training_package_rejects_empty_folds(tmp_path: Path) -> None:
    # Given: a complete request without a walk-forward evaluation protocol.
    request = _request(tmp_path)

    # When / Then: no preprocessing or experiment evidence is published.
    with pytest.raises(TrainingPackageError, match="folds are empty"):
        build_training_package(request, (), training_frame())


def test_training_package_rejects_column_source_reordering(tmp_path: Path) -> None:
    # Given: field-level sources that omit one physical training column.
    request = _request(tmp_path)
    request = replace(request, column_sources=request.column_sources[:-1])

    # When / Then: schema and lineage cannot be silently aligned by name later.
    with pytest.raises(TrainingPackageError, match="physical training frame"):
        build_training_package(request, folds(), training_frame())


def test_training_package_rejects_feature_absent_from_dataset(tmp_path: Path) -> None:
    # Given: an experiment asks for a feature absent from its DatasetSpec.
    request = replace(_request(tmp_path), feature_names=("unknown_factor",))

    # When / Then: the package refuses to fit a dynamically injected column.
    with pytest.raises(TrainingPackageError, match="absent from DatasetSpec"):
        build_training_package(request, folds(), training_frame())


def test_training_package_rejects_label_different_from_dataset(tmp_path: Path) -> None:
    # Given: an experiment declares a different target than the frozen DatasetSpec.
    request = replace(_request(tmp_path), label_name="other_label")

    # When / Then: training stops before any fold-local fitting.
    with pytest.raises(TrainingPackageError, match="label differs"):
        build_training_package(request, folds(), training_frame())
