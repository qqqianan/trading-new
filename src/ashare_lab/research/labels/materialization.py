"""Immutable publication of the provenance-rich future label."""

import hashlib
from datetime import datetime

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ArtifactFieldMapping,
    ArtifactKind,
    ArtifactWriteRequest,
    ParquetArtifactStore,
    ResearchSchemaCatalog,
)
from ashare_lab.research.labels.catalog import medium_horizon_label
from ashare_lab.research.labels.models import RelativeReturnLabelRow


class LabelMaterializationRequest(BaseModel):
    """Closed input, universe, lineage, and code identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_manifest_id: str = Field(pattern=r"^inputs_[0-9A-Za-z_]+$")
    input_lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9A-Za-z_]+$")
    universe_artifact_id: str = Field(pattern=r"^universe_artifact_[0-9A-Za-z_]+$")
    universe_lineage_edge_id: str = Field(pattern=r"^lineage_[0-9A-Za-z_]+$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


def label_frame(
    schemas: ResearchSchemaCatalog,
    rows: tuple[RelativeReturnLabelRow, ...],
) -> pl.DataFrame:
    """Convert typed label rows to the exact isolated physical schema."""
    return pl.DataFrame(
        data=[_row_values(row) for row in rows],
        schema=schemas.polars_schema(ArtifactKind.LABEL),
        orient="row",
    )


def materialize_label_rows(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    rows: tuple[RelativeReturnLabelRow, ...],
    request: LabelMaterializationRequest,
) -> ArtifactDescriptor:
    """Publish one complete long-form label artifact with field mappings."""
    return materialize_label_frame(store, schemas, label_frame(schemas, rows), request)


def materialize_label_frame(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    frame: pl.DataFrame,
    request: LabelMaterializationRequest,
) -> ArtifactDescriptor:
    """Publish one preassembled label frame without loading all rows as objects."""
    definition = medium_horizon_label()
    parameters = hashlib.sha256(
        f"{definition.model_dump_json()}|raw_open_execution_filter_1.0.0".encode()
    ).hexdigest()
    schema = schemas.schema(ArtifactKind.LABEL)
    return store.write(
        frame,
        ArtifactWriteRequest(
            kind=ArtifactKind.LABEL,
            schema_manifest_id=schema.manifest_id,
            upstream_artifact_ids=(request.input_manifest_id, request.universe_artifact_id),
            upstream_lineage_edge_ids=(
                request.input_lineage_manifest_id,
                request.universe_lineage_edge_id,
            ),
            field_mappings=_field_mappings(request, tuple(frame.columns)),
            transform_name="relative_open_return_label",
            transform_version=definition.version,
            parameters_sha256=parameters,
            code_commit=request.code_commit,
        ),
    )


def _row_values(row: RelativeReturnLabelRow) -> tuple[str | float | datetime | None, ...]:
    return (
        row.symbol,
        row.decision_time,
        row.entry_time,
        row.exit_time,
        row.label_id,
        row.label_version,
        row.value,
        row.available_at,
        row.null_reason,
        row.entry_price_source_snapshot_id,
        row.entry_price_source_row_sha256,
        row.entry_constraint_source_snapshot_id,
        row.entry_constraint_source_row_sha256,
        row.exit_price_source_snapshot_id,
        row.exit_price_source_row_sha256,
        row.exit_constraint_source_snapshot_id,
        row.exit_constraint_source_row_sha256,
        row.benchmark_entry_source_snapshot_id,
        row.benchmark_entry_source_row_sha256,
        row.benchmark_exit_source_snapshot_id,
        row.benchmark_exit_source_row_sha256,
    )


def _field_mappings(
    request: LabelMaterializationRequest,
    columns: tuple[str, ...],
) -> tuple[ArtifactFieldMapping, ...]:
    universe_fields = {"symbol", "decision_time"}
    return tuple(
        ArtifactFieldMapping(
            output_field=column,
            upstream_artifact_id=(
                request.universe_artifact_id
                if column in universe_fields
                else request.input_manifest_id
            ),
            upstream_field=_upstream_field(column),
            transformation=_transformation(column),
        )
        for column in columns
    )


def _upstream_field(column: str) -> str:
    if column in {"symbol", "decision_time"}:
        return f"universe.{column}"
    if "benchmark" in column:
        return f"canonical_index_daily_bar.{column}"
    if "source" in column:
        return f"canonical_daily_execution_bundle.{column}"
    return f"label_definition.{column}"


def _transformation(column: str) -> str:
    if column in {"symbol", "decision_time"}:
        return "identity_join"
    if "source" in column:
        return "exact_selected_raw_lineage"
    return "fixed_trading_session_relative_return"
