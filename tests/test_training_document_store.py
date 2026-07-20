from pathlib import Path

import pytest

from ashare_lab.research.model_evidence import TrainingFieldSchema, TrainingSchemaDocument
from ashare_lab.research.training.document_store import (
    TrainingDocumentStore,
    TrainingDocumentStoreError,
)


def _schema() -> TrainingSchemaDocument:
    return TrainingSchemaDocument(
        dataset_snapshot_id="ds_abc123",
        feature_names=("factor_a",),
        size_feature_name="factor_a",
        label_name="label_a",
        fields=(
            TrainingFieldSchema(
                field_name="factor_a",
                data_type="float64",
                nullable=True,
                unit="ratio",
                null_semantics="missing source",
                time_role="as_of_decision_time",
                allowed_use="model_feature_only",
                source_schema_manifest_id="schema_" + "a" * 64,
            ),
        ),
    )


def test_training_document_store_rejects_altered_existing_bytes(tmp_path: Path) -> None:
    # Given: an immutable schema document whose stored bytes were altered.
    store = TrainingDocumentStore(tmp_path)
    descriptor = store.write("training_schema", _schema())
    descriptor.path.write_text("{}\n", encoding="utf-8")

    # When / Then: a repeated publication detects the content conflict.
    with pytest.raises(TrainingDocumentStoreError, match="bytes differ"):
        store.write("training_schema", _schema())


def test_training_document_store_rejects_missing_existing_manifest(tmp_path: Path) -> None:
    # Given: a content-addressed directory whose manifest disappeared.
    store = TrainingDocumentStore(tmp_path)
    descriptor = store.write("training_schema", _schema())
    descriptor.path.unlink()

    # When / Then: the directory cannot be treated as a completed artifact.
    with pytest.raises(TrainingDocumentStoreError, match="cannot read"):
        store.write("training_schema", _schema())
