"""Immutable financial feature publication with selected-version lineage."""

import hashlib

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
from ashare_lab.research.features.financial.catalog import financial_factor_catalog
from ashare_lab.research.features.financial.models import FinancialFactorValue


class FinancialFeatureMaterializationRequest(BaseModel):
    """Closed input, universe, lineage, and code identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_manifest_id: str = Field(pattern=r"^inputs_[0-9A-Za-z_]+$")
    input_lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9A-Za-z_]+$")
    universe_artifact_id: str = Field(pattern=r"^universe_artifact_[0-9A-Za-z_]+$")
    universe_lineage_edge_id: str = Field(pattern=r"^lineage_[0-9A-Za-z_]+$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


def materialize_financial_factor_artifacts(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    rows: tuple[FinancialFactorValue, ...],
    request: FinancialFeatureMaterializationRequest,
) -> tuple[ArtifactDescriptor, ...]:
    """Partition one long-form batch into six isolated factor artifacts."""
    return tuple(
        materialize_financial_factor_frame(
            store,
            schemas,
            financial_factor_frame(
                schemas,
                tuple(row for row in rows if row.feature_id == definition.name),
            ),
            definition.name,
            request,
        )
        for definition in financial_factor_catalog()
    )


def financial_factor_frame(
    schemas: ResearchSchemaCatalog,
    rows: tuple[FinancialFactorValue, ...],
) -> pl.DataFrame:
    """Convert typed financial rows to the exact provenance-rich schema."""
    return pl.DataFrame(
        data=[
            (
                row.symbol,
                row.decision_time,
                row.feature_id,
                row.feature_version,
                row.value,
                row.available_at,
                row.quality_status,
                row.null_reason,
                row.source_event_id,
                row.source_report_period,
                row.source_available_at,
                row.source_update_flag,
                row.source_snapshot_id,
                row.source_row_sha256,
            )
            for row in rows
        ],
        schema=schemas.polars_schema(ArtifactKind.FEATURE),
        orient="row",
    )


def materialize_financial_factor_frame(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    frame: pl.DataFrame,
    feature_id: str,
    request: FinancialFeatureMaterializationRequest,
) -> ArtifactDescriptor:
    """Publish one preassembled financial factor with full field mappings."""
    definition = next(item for item in financial_factor_catalog() if item.name == feature_id)
    parameters = hashlib.sha256(
        f"{definition.model_dump_json()}|financial_pit_selector_1.0.0".encode()
    ).hexdigest()
    return store.write(
        frame,
        ArtifactWriteRequest(
            kind=ArtifactKind.FEATURE,
            schema_manifest_id=schemas.schema(ArtifactKind.FEATURE).manifest_id,
            upstream_artifact_ids=(request.input_manifest_id, request.universe_artifact_id),
            upstream_lineage_edge_ids=(
                request.input_lineage_manifest_id,
                request.universe_lineage_edge_id,
            ),
            field_mappings=_field_mappings(request, feature_id),
            transform_name=f"financial_factor_{feature_id}",
            transform_version=definition.version,
            parameters_sha256=parameters,
            code_commit=request.code_commit,
        ),
    )


def _field_mappings(
    request: FinancialFeatureMaterializationRequest,
    feature_id: str,
) -> tuple[ArtifactFieldMapping, ...]:
    fields = (
        ("symbol", request.universe_artifact_id, "universe.symbol", "identity_join"),
        ("decision_time", request.universe_artifact_id, "universe.decision_time", "identity_join"),
        ("feature_id", request.input_manifest_id, feature_id, "registered_constant"),
        ("feature_version", request.input_manifest_id, feature_id, "registered_constant"),
        (
            "value",
            request.input_manifest_id,
            f"pit_financial_indicators.{feature_id}",
            "asof_version",
        ),
        (
            "available_at",
            request.input_manifest_id,
            "pit_and_universe.available_at",
            "maximum_clock",
        ),
        ("quality_status", request.input_manifest_id, "quality_reports", "factor_quality"),
        ("null_reason", request.input_manifest_id, feature_id, "stable_reason"),
        (
            "source_event_id",
            request.input_manifest_id,
            "pit_financial_indicators.event_id",
            "asof_version",
        ),
        (
            "source_report_period",
            request.input_manifest_id,
            "pit_financial_indicators.end_date",
            "asof_version",
        ),
        (
            "source_available_at",
            request.input_manifest_id,
            "pit_financial_indicators.available_at",
            "asof_version",
        ),
        (
            "source_update_flag",
            request.input_manifest_id,
            "pit_financial_indicators.update_flag",
            "asof_version",
        ),
        (
            "source_snapshot_id",
            request.input_manifest_id,
            "pit_financial_indicators.source_snapshot_id",
            "lineage",
        ),
        (
            "source_row_sha256",
            request.input_manifest_id,
            "pit_financial_indicators.source_row_sha256",
            "lineage",
        ),
    )
    return tuple(
        ArtifactFieldMapping(
            output_field=output,
            upstream_artifact_id=upstream,
            upstream_field=field,
            transformation=transform,
        )
        for output, upstream, field, transform in fields
    )
