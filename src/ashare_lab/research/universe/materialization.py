"""Immutable Parquet publication of governed weekly universe panels."""

import hashlib
from typing import Final

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
from ashare_lab.research.universe.models import (
    UniverseAdmissionSpec,
    UniversePanelRow,
)

_DEFAULT_SPEC: Final = UniverseAdmissionSpec()


class UniverseMaterializationRequest(BaseModel):
    """Qualified upstream closure and reproducible code identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_manifest_id: str = Field(pattern=r"^inputs_[0-9A-Za-z_]+$")
    input_lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9A-Za-z_]+$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


def materialize_universe_panel(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    rows: tuple[UniversePanelRow, ...],
    request: UniverseMaterializationRequest,
    spec: UniverseAdmissionSpec = _DEFAULT_SPEC,
) -> ArtifactDescriptor:
    """Publish one exact-schema panel from a qualified input manifest closure."""
    frame = universe_panel_frame(schemas, rows)
    return materialize_universe_frame(store, schemas, frame, request, spec)


def universe_panel_frame(
    schemas: ResearchSchemaCatalog,
    rows: tuple[UniversePanelRow, ...],
) -> pl.DataFrame:
    """Convert typed panel rows to the exact registered physical schema."""
    kind = ArtifactKind.UNIVERSE
    return pl.DataFrame(
        data=[
            (
                row.symbol,
                row.decision_time,
                row.available_at,
                row.eligible_for_new_risk,
                row.must_continue_marking,
                list(row.reason_codes),
            )
            for row in rows
        ],
        schema=schemas.polars_schema(kind),
        orient="row",
    )


def materialize_universe_frame(
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    frame: pl.DataFrame,
    request: UniverseMaterializationRequest,
    spec: UniverseAdmissionSpec = _DEFAULT_SPEC,
) -> ArtifactDescriptor:
    """Publish a preassembled exact-schema frame as one immutable artifact."""
    kind = ArtifactKind.UNIVERSE
    parameters_sha256 = hashlib.sha256(spec.version_id.encode()).hexdigest()
    write_request = ArtifactWriteRequest(
        kind=kind,
        schema_manifest_id=schemas.schema(kind).manifest_id,
        upstream_artifact_ids=(request.input_manifest_id,),
        upstream_lineage_edge_ids=(request.input_lineage_manifest_id,),
        field_mappings=_field_mappings(request.input_manifest_id),
        transform_name="weekly_pit_universe_materialization",
        transform_version=spec.rule_version,
        parameters_sha256=parameters_sha256,
        code_commit=request.code_commit,
    )
    return store.write(frame, write_request)


def _field_mappings(input_manifest_id: str) -> tuple[ArtifactFieldMapping, ...]:
    fields = (
        ("symbol", "pit_security_events.ts_code", "pit_lifecycle_replay"),
        ("decision_time", "canonical_trade_calendar.cal_date", "weekly_last_open_at_1800"),
        (
            "available_at",
            "pit_and_market.available_at",
            "maximum_visible_evidence_clock",
        ),
        (
            "eligible_for_new_risk",
            "pit_security_events+canonical_daily_bar",
            "versioned_admission_rules",
        ),
        (
            "must_continue_marking",
            "pit_security_events.ts_code",
            "ever_listed_accounting_duty",
        ),
        (
            "reason_codes",
            "pit_security_events+canonical_daily_bar",
            "stable_fail_closed_reason_codes",
        ),
    )
    return tuple(
        ArtifactFieldMapping(
            output_field=output,
            upstream_artifact_id=input_manifest_id,
            upstream_field=upstream,
            transformation=transformation,
        )
        for output, upstream, transformation in fields
    )
