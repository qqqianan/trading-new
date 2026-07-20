"""Deterministic schema, lineage, preprocessing, and experiment package assembly."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.datasets.spec_store import DatasetSpecDescriptor
from ashare_lab.research.experiments.manifest import ExperimentManifest, ModelFamily
from ashare_lab.research.model_evidence import (
    DevelopmentTrainingEvidence,
    ModelPurpose,
    TrainingDataKind,
    TrainingFieldLineage,
    TrainingLineageDocument,
)
from ashare_lab.research.preprocessing import FoldPreprocessor
from ashare_lab.research.preprocessing.models import FoldPreprocessorDescriptor
from ashare_lab.research.preprocessing.store import FoldPreprocessorStore
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256
from ashare_lab.research.splits.final_holdout import FinalHoldoutSpec
from ashare_lab.research.splits.walk_forward import DEVELOPMENT_END, WalkForwardFold
from ashare_lab.research.training.document_store import TrainingDocumentStore
from ashare_lab.research.training.package_schema import build_training_schema


@dataclass(frozen=True, slots=True)
class TrainingColumnSource:
    """Exact source artifact and row schema for one physical training column."""

    field_name: str
    artifact_id: str
    schema_manifest_id: str


@dataclass(frozen=True, slots=True)
class TrainingPackageRequest:
    """Frozen real-data identities required to prepare one Ridge experiment."""

    artifact_root: Path
    holdout_ledger_root: Path
    dataset_descriptor: DatasetSpecDescriptor
    dataset_spec: DatasetSpec
    feature_names: tuple[str, ...]
    size_feature_name: str
    label_name: str
    label_version: str
    column_sources: tuple[TrainingColumnSource, ...]
    git_commit: str
    trial_batch_id: str
    factor_report_id: str
    portfolio_backtest_id: str
    portfolio_rule_version: str
    cost_rule_version: str


@dataclass(frozen=True, slots=True)
class GovernedTrainingPackage:
    """Complete immutable inputs accepted by the sole TrainingService."""

    evidence: DevelopmentTrainingEvidence
    experiment: ExperimentManifest


class TrainingPackageError(Exception):
    """Frozen inputs cannot form a complete development training package."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed package-assembly failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the package boundary and blocker."""
        return f"training_package: {self.detail}"


def build_training_package(
    request: TrainingPackageRequest,
    folds: tuple[WalkForwardFold, ...],
    frame: pl.DataFrame,
) -> GovernedTrainingPackage:
    """Materialize deterministic development-only evidence before fitting."""
    _validate_request(request, folds, frame)
    store = TrainingDocumentStore(request.artifact_root)
    schema = build_training_schema(
        request.dataset_spec.snapshot_id,
        request.feature_names,
        request.size_feature_name,
        request.label_name,
        request.column_sources,
    )
    schema_descriptor = store.write("training_schema", schema)
    lineage = TrainingLineageDocument(
        lineage_manifest_id=request.dataset_spec.lineage_manifest_id,
        dataset_snapshot_id=request.dataset_spec.snapshot_id,
        fields=tuple(
            TrainingFieldLineage(
                field_name=source.field_name,
                source_artifact_ids=(source.artifact_id,),
                raw_snapshot_ids=request.dataset_spec.source_snapshot_ids,
            )
            for source in request.column_sources
        ),
    )
    lineage_descriptor = store.write("training_lineage", lineage)
    preprocessor_store = FoldPreprocessorStore(request.artifact_root)
    preprocessor = FoldPreprocessor(request.feature_names, request.size_feature_name)
    descriptors = tuple(
        preprocessor_store.write(
            preprocessor.fit(
                frame.filter(pl.col("decision_time").dt.date().is_in(fold.train)),
                f"fold_{fold.fold_index:03d}",
                request.dataset_spec.snapshot_id,
            )
        )
        for fold in folds
    )
    run_id = _training_run_id(
        request, schema_descriptor.data_sha256, lineage_descriptor.data_sha256, descriptors
    )
    experiment = ExperimentManifest(
        training_run_id=run_id,
        dataset_snapshot_id=request.dataset_spec.snapshot_id,
        schema_manifest_id=f"schema_{schema_descriptor.data_sha256}",
        lineage_manifest_id=request.dataset_spec.lineage_manifest_id,
        rulebook_version=request.dataset_spec.rulebook_version,
        git_commit=request.git_commit,
        model_family=ModelFamily.RIDGE,
        feature_names=request.feature_names,
        size_feature_name=request.size_feature_name,
        label_name=request.label_name,
        split_protocol="purged_walk_forward_medium_horizon_v1",
        random_seed=7,
        final_test_runs=0,
        ridge_alphas=(0.1, 1.0, 10.0, 100.0),
        preprocessor_artifact_ids=tuple(item.artifact_id for item in descriptors),
        trial_batch_id=request.trial_batch_id,
        portfolio_rule_version=request.portfolio_rule_version,
        cost_rule_version=request.cost_rule_version,
    )
    holdout = FinalHoldoutSpec(
        dataset_snapshot_id=request.dataset_spec.snapshot_id,
        development_end=DEVELOPMENT_END,
        holdout_start=date(2025, 1, 1),
        protocol_version="1.0.0",
    )
    evidence = DevelopmentTrainingEvidence(
        purpose=ModelPurpose.INVESTMENT_DECISION,
        data_kind=TrainingDataKind.GOVERNED_REAL,
        artifact_root=request.artifact_root,
        dataset_descriptor=request.dataset_descriptor,
        schema_descriptor=schema_descriptor,
        lineage_descriptor=lineage_descriptor,
        preprocessor_descriptors=descriptors,
        development_data_sha256=training_frame_sha256(frame),
        holdout_ledger_root=request.holdout_ledger_root,
        holdout_spec_id=holdout.spec_id,
    )
    return GovernedTrainingPackage(evidence, experiment)


def _validate_request(
    request: TrainingPackageRequest,
    folds: tuple[WalkForwardFold, ...],
    frame: pl.DataFrame,
) -> None:
    if not folds:
        detail = "development folds are empty"
        raise TrainingPackageError(detail)
    if tuple(item.field_name for item in request.column_sources) != tuple(frame.columns):
        detail = "column sources differ from the physical training frame"
        raise TrainingPackageError(detail)
    spec_features = {item.name: item.version for item in request.dataset_spec.features}
    required_features = {*request.feature_names, request.size_feature_name}
    if required_features - set(spec_features):
        detail = "model features are absent from DatasetSpec"
        raise TrainingPackageError(detail)
    if (
        request.dataset_spec.label.name != request.label_name
        or request.dataset_spec.label.version != request.label_version
    ):
        detail = "label differs from DatasetSpec"
        raise TrainingPackageError(detail)


def _training_run_id(
    request: TrainingPackageRequest,
    schema_sha: str,
    lineage_sha: str,
    descriptors: tuple[FoldPreprocessorDescriptor, ...],
) -> str:
    payload = {
        "dataset": request.dataset_spec.snapshot_id,
        "features": request.feature_names,
        "factor_report": request.factor_report_id,
        "git_commit": request.git_commit,
        "lineage_sha256": lineage_sha,
        "preprocessors": tuple(item.artifact_id for item in descriptors),
        "portfolio_backtest": request.portfolio_backtest_id,
        "schema_sha256": schema_sha,
        "trial_batch": request.trial_batch_id,
    }
    content = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return f"ridge_run_{hashlib.sha256(content).hexdigest()}"
