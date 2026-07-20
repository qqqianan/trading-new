"""Typed documents and byte verification for development training evidence."""

import hashlib
from datetime import date

import polars as pl
from pydantic import BaseModel, ValidationError

from ashare_lab.research.datasets.spec_store import (
    DatasetSpecStore,
    DatasetSpecStoreError,
)
from ashare_lab.research.experiments.manifest import ExperimentManifest
from ashare_lab.research.model_evidence_models import (
    ContentDocumentDescriptor,
    DevelopmentTrainingEvidence,
    ModelPurpose,
    TrainingDataKind,
    TrainingEvidenceError,
    TrainingFieldLineage,
    TrainingLineageDocument,
    TrainingSchemaDocument,
    VerifiedDevelopmentInputs,
)
from ashare_lab.research.preprocessing.models import (
    FoldPreprocessingArtifact,
)
from ashare_lab.research.preprocessing.store import (
    FoldPreprocessorStore,
    FoldPreprocessorStoreError,
)
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256
from ashare_lab.research.splits.walk_forward import DEVELOPMENT_END, WalkForwardFold

__all__ = [
    "ContentDocumentDescriptor",
    "DevelopmentTrainingEvidence",
    "ModelPurpose",
    "TrainingDataKind",
    "TrainingFieldLineage",
    "TrainingLineageDocument",
    "TrainingSchemaDocument",
]


def verify_development_evidence(
    evidence: DevelopmentTrainingEvidence,
    experiment: ExperimentManifest,
    folds: tuple[WalkForwardFold, ...],
    frame: pl.DataFrame,
) -> VerifiedDevelopmentInputs:
    """Recompute every identity and reject evidence inconsistent with the experiment."""
    try:
        spec = DatasetSpecStore(evidence.artifact_root).read(evidence.dataset_descriptor)
    except DatasetSpecStoreError as error:
        rule = "dataset_spec"
        raise TrainingEvidenceError(rule, str(error)) from error
    if (
        spec.snapshot_id != experiment.dataset_snapshot_id
        or spec.lineage_manifest_id != experiment.lineage_manifest_id
    ):
        rule = "dataset_identity"
        detail = "experiment differs from DatasetSpec"
        raise TrainingEvidenceError(rule, detail)
    schema = _read_document(evidence.schema_descriptor, TrainingSchemaDocument, "training_schema")
    lineage = _read_document(
        evidence.lineage_descriptor,
        TrainingLineageDocument,
        "training_lineage",
    )
    if (
        f"schema_{evidence.schema_descriptor.data_sha256}" != experiment.schema_manifest_id
        or schema.dataset_snapshot_id != experiment.dataset_snapshot_id
        or schema.feature_names != experiment.feature_names
        or schema.size_feature_name != experiment.size_feature_name
        or schema.label_name != experiment.label_name
    ):
        rule = "training_schema"
        detail = "schema differs from experiment"
        raise TrainingEvidenceError(rule, detail)
    expected_fields = (
        *experiment.feature_names,
        experiment.size_feature_name,
        experiment.label_name,
    )
    if (
        lineage.lineage_manifest_id != experiment.lineage_manifest_id
        or lineage.dataset_snapshot_id != experiment.dataset_snapshot_id
        or tuple(item.field_name for item in lineage.fields) != expected_fields
    ):
        rule = "training_lineage"
        detail = "field lineage is incomplete or reordered"
        raise TrainingEvidenceError(rule, detail)
    if training_frame_sha256(frame) != evidence.development_data_sha256:
        rule = "development_data"
        detail = "training frame bytes differ"
        raise TrainingEvidenceError(rule, detail)
    maximum_date = frame["decision_time"].dt.date().max()
    match maximum_date:
        case date() as latest_date:
            if latest_date > DEVELOPMENT_END:
                rule = "final_holdout_sealed"
                detail = "frame crosses development end"
                raise TrainingEvidenceError(rule, detail)
        case _:
            rule = "development_data"
            detail = "frame has no valid decision date"
            raise TrainingEvidenceError(rule, detail)
    preprocessors = _read_preprocessors(evidence, experiment, folds)
    return VerifiedDevelopmentInputs(spec, preprocessors)


def _read_preprocessors(
    evidence: DevelopmentTrainingEvidence,
    experiment: ExperimentManifest,
    folds: tuple[WalkForwardFold, ...],
) -> tuple[FoldPreprocessingArtifact, ...]:
    if (
        len(evidence.preprocessor_descriptors) != len(folds)
        or tuple(item.artifact_id for item in evidence.preprocessor_descriptors)
        != experiment.preprocessor_artifact_ids
    ):
        rule = "fold_preprocessors"
        detail = "preprocessor identities differ"
        raise TrainingEvidenceError(rule, detail)
    store = FoldPreprocessorStore(evidence.artifact_root)
    values: list[FoldPreprocessingArtifact] = []
    try:
        for fold, descriptor in zip(folds, evidence.preprocessor_descriptors, strict=True):
            artifact = store.read(descriptor)
            if (
                artifact.fold_id != f"fold_{fold.fold_index:03d}"
                or artifact.dataset_snapshot_id != experiment.dataset_snapshot_id
                or artifact.feature_names != experiment.feature_names
                or artifact.size_feature_name != experiment.size_feature_name
                or artifact.training_start.date() != fold.train[0]
                or artifact.training_end.date() != fold.train[-1]
            ):
                rule = "fold_preprocessors"
                detail = "preprocessor scope differs from fold"
                raise TrainingEvidenceError(rule, detail)
            values.append(artifact)
    except FoldPreprocessorStoreError as error:
        rule = "fold_preprocessors"
        raise TrainingEvidenceError(rule, str(error)) from error
    return tuple(values)


def _read_document[Document: BaseModel](
    descriptor: ContentDocumentDescriptor,
    model: type[Document],
    rule: str,
) -> Document:
    try:
        content = descriptor.path.read_bytes()
        document = model.model_validate_json(content)
    except (OSError, ValidationError) as error:
        raise TrainingEvidenceError(rule, "document is missing or invalid") from error
    if hashlib.sha256(content).hexdigest() != descriptor.data_sha256:
        raise TrainingEvidenceError(rule, "document bytes differ from descriptor")
    return document
