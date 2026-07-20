"""Complete physical and semantic schema for an exact model training frame."""

from typing import Protocol

from ashare_lab.research.model_evidence import TrainingFieldSchema, TrainingSchemaDocument


class TrainingSchemaSource(Protocol):
    """Source fields required to document one physical training column."""

    @property
    def field_name(self) -> str:
        """Return the physical training column name."""
        ...

    @property
    def schema_manifest_id(self) -> str:
        """Return the source row schema identity."""
        ...


def build_training_schema(
    dataset_snapshot_id: str,
    feature_names: tuple[str, ...],
    size_feature_name: str,
    label_name: str,
    column_sources: tuple[TrainingSchemaSource, ...],
) -> TrainingSchemaDocument:
    """Document every physical frame column in exact persisted order."""
    return TrainingSchemaDocument(
        dataset_snapshot_id=dataset_snapshot_id,
        feature_names=feature_names,
        size_feature_name=size_feature_name,
        label_name=label_name,
        fields=tuple(_field_schema(source, label_name) for source in column_sources),
    )


def _field_schema(source: TrainingSchemaSource, label_name: str) -> TrainingFieldSchema:
    name = source.field_name
    is_key = name in {"decision_time", "symbol"}
    return TrainingFieldSchema(
        field_name=name,
        data_type=(
            "datetime_asia_shanghai"
            if name == "decision_time"
            else "string"
            if name == "symbol"
            else "float64"
        ),
        nullable=not is_key,
        unit=(
            "Asia/Shanghai"
            if name == "decision_time"
            else "tushare_ts_code"
            if name == "symbol"
            else "simple_relative_return"
            if name == label_name
            else "feature_defined"
        ),
        null_semantics=(
            "never null" if is_key else "null preserves unavailable governed source evidence"
        ),
        time_role=(
            "decision_time"
            if name == "decision_time"
            else "entity_key"
            if name == "symbol"
            else "future_label_window"
            if name == label_name
            else "as_of_decision_time"
        ),
        allowed_use=(
            "training_key"
            if is_key
            else "training_target_only"
            if name == label_name
            else "model_feature_only"
        ),
        source_schema_manifest_id=source.schema_manifest_id,
    )
