from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.artifacts import (
    ArtifactKind,
    ResearchArtifactError,
    ResearchSchemaCatalog,
)

ROOT = Path(__file__).parents[1]
SCHEMA_PATHS = tuple(sorted((ROOT / "schemas").glob("research_*_row_v1.json")))


def test_research_schema_catalog_registers_all_materialized_row_kinds() -> None:
    # Given: the committed machine-readable research row contracts.
    # When: the catalog parses and content-addresses every schema.
    catalog = ResearchSchemaCatalog.load(SCHEMA_PATHS)

    # Then: every materialized boundary kind is registered.
    assert catalog.kinds == (
        ArtifactKind.DATASET,
        ArtifactKind.FEATURE,
        ArtifactKind.LABEL,
        ArtifactKind.UNIVERSE,
    )
    assert len(catalog.schemas(ArtifactKind.FEATURE)) == 2


def test_research_schema_rejects_null_in_required_field() -> None:
    # Given: a feature row whose required symbol is null.
    catalog = ResearchSchemaCatalog.load(SCHEMA_PATHS)
    feature_schema = next(
        schema for schema in catalog.schemas(ArtifactKind.FEATURE) if len(schema.fields) == 8
    )
    available_at = datetime(2026, 7, 16, 18, tzinfo=ZoneInfo("Asia/Shanghai"))
    frame = pl.DataFrame(
        {
            "symbol": [None],
            "decision_time": [available_at],
            "feature_id": ["mom_20"],
            "feature_version": ["1.0.0"],
            "value": [1.5],
            "available_at": [available_at],
            "quality_status": ["ACCEPTED"],
            "null_reason": [None],
        },
        schema=catalog.polars_schema(ArtifactKind.FEATURE, feature_schema.manifest_id),
    )

    # When / Then: nullable metadata is enforced, not merely documented.
    with pytest.raises(ResearchArtifactError, match="schema_mismatch"):
        catalog.validate(ArtifactKind.FEATURE, frame, feature_schema.manifest_id)


def test_research_schema_documents_training_semantics_for_every_field() -> None:
    # Given: every committed row schema.
    catalog = ResearchSchemaCatalog.load(SCHEMA_PATHS)

    # When: field documentation is inspected through the typed registry.
    fields = tuple(
        field
        for kind in catalog.kinds
        for schema in catalog.schemas(kind)
        for field in schema.fields
    )

    # Then: training cannot encounter an undocumented type, unit, null, time, or use role.
    assert fields
    assert all(
        field.unit and field.null_semantics and field.time_role and field.allowed_use
        for field in fields
    )
