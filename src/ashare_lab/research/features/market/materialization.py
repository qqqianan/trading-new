"""Immutable per-factor Parquet publication with structured field lineage."""

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
from ashare_lab.research.features.market.catalog import market_factor_catalog
from ashare_lab.research.features.market.models import MarketFactorRow


class MarketFeatureMaterializationRequest(BaseModel):
    """Closed upstream data, universe, lineage, and code identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_manifest_id: str = Field(pattern=r"^inputs_[0-9A-Za-z_]+$")
    input_lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9A-Za-z_]+$")
    universe_artifact_id: str = Field(pattern=r"^universe_artifact_[0-9A-Za-z_]+$")
    universe_lineage_edge_id: str = Field(pattern=r"^lineage_[0-9A-Za-z_]+$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


def materialize_market_factor_artifacts(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    rows: tuple[MarketFactorRow, ...],
    request: MarketFeatureMaterializationRequest,
) -> tuple[ArtifactDescriptor, ...]:
    """Partition long-form rows into one immutable artifact per feature."""
    descriptors: list[ArtifactDescriptor] = []
    for definition in market_factor_catalog():
        feature_rows = tuple(row for row in rows if row.feature_id == definition.name)
        descriptors.append(
            materialize_market_factor_frame(
                store,
                schemas,
                market_factor_frame(schemas, feature_rows),
                definition.name,
                request,
            )
        )
    return tuple(descriptors)


def market_factor_frame(
    schemas: ResearchSchemaCatalog,
    rows: tuple[MarketFactorRow, ...],
) -> pl.DataFrame:
    """Convert typed rows to the exact registered feature schema."""
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
            )
            for row in rows
        ],
        schema=schemas.polars_schema(ArtifactKind.FEATURE),
        orient="row",
    )


def materialize_market_factor_frame(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    frame: pl.DataFrame,
    feature_id: str,
    request: MarketFeatureMaterializationRequest,
) -> ArtifactDescriptor:
    """Publish one preassembled factor frame with its exact lineage mapping."""
    definition = next(item for item in market_factor_catalog() if item.name == feature_id)
    parameters = hashlib.sha256(
        f"{definition.model_dump_json()}|market_formula_1.0.0".encode()
    ).hexdigest()
    return store.write(
        frame,
        ArtifactWriteRequest(
            kind=ArtifactKind.FEATURE,
            schema_manifest_id=schemas.schema(ArtifactKind.FEATURE).manifest_id,
            upstream_artifact_ids=(
                request.input_manifest_id,
                request.universe_artifact_id,
            ),
            upstream_lineage_edge_ids=(
                request.input_lineage_manifest_id,
                request.universe_lineage_edge_id,
            ),
            field_mappings=_field_mappings(request, definition.name),
            transform_name=f"market_factor_{definition.name}",
            transform_version=definition.version,
            parameters_sha256=parameters,
            code_commit=request.code_commit,
        ),
    )


def _field_mappings(
    request: MarketFeatureMaterializationRequest,
    feature_id: str,
) -> tuple[ArtifactFieldMapping, ...]:
    mappings = (
        ("symbol", request.universe_artifact_id, "universe.symbol", "identity_join"),
        (
            "decision_time",
            request.universe_artifact_id,
            "universe.decision_time",
            "identity_join",
        ),
        ("feature_id", request.input_manifest_id, feature_id, "registered_constant"),
        ("feature_version", request.input_manifest_id, feature_id, "registered_constant"),
        ("value", request.input_manifest_id, "five_chain_market_fields", feature_id),
        (
            "available_at",
            request.input_manifest_id,
            "five_chain.available_at",
            "maximum_used_source_clock",
        ),
        ("quality_status", request.input_manifest_id, "quality_reports", "factor_quality"),
        ("null_reason", request.input_manifest_id, "bundle_and_formula_status", "stable_reason"),
    )
    return tuple(
        ArtifactFieldMapping(
            output_field=output,
            upstream_artifact_id=upstream_id,
            upstream_field=upstream_field,
            transformation=transformation,
        )
        for output, upstream_id, upstream_field, transformation in mappings
    )
