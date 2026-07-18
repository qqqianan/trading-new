"""Content-addressed registry for exact research Parquet row schemas."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from pydantic import ValidationError

from ashare_lab.research.artifacts.models import (
    ArtifactKind,
    ArtifactRule,
    ResearchArtifactError,
)
from ashare_lab.research.artifacts.schema_models import (
    ResearchFieldSchema,
    ResearchFieldType,
    ResearchRowSchemaDocument,
)


@dataclass(frozen=True, slots=True)
class RegisteredResearchSchema:
    """One parsed row schema bound to its exact committed bytes."""

    manifest_id: str
    schema_version: str
    artifact_kind: ArtifactKind
    fields: tuple[ResearchFieldSchema, ...]


class ResearchSchemaCatalog:
    """Content-addressed lookup supporting exact schemas within one kind."""

    def __init__(self, schemas: tuple[RegisteredResearchSchema, ...]) -> None:
        """Create a catalog after duplicate manifest IDs have been rejected."""
        identities = tuple(schema.manifest_id for schema in schemas)
        if len(identities) != len(set(identities)):
            raise ResearchArtifactError(
                ArtifactRule.INVALID_SCHEMA,
                "research schema manifest IDs must be unique",
            )
        self._schemas = schemas
        self._by_id = {schema.manifest_id: schema for schema in schemas}

    @classmethod
    def load(cls, paths: tuple[Path, ...]) -> "ResearchSchemaCatalog":
        """Parse and content-address committed research schema documents."""
        schemas: list[RegisteredResearchSchema] = []
        for path in paths:
            try:
                content = path.read_bytes()
                document = ResearchRowSchemaDocument.model_validate_json(content)
            except (FileNotFoundError, ValidationError) as error:
                raise ResearchArtifactError(
                    ArtifactRule.INVALID_SCHEMA,
                    f"research row schema is missing or invalid: {path}",
                ) from error
            digest = hashlib.sha256(content).hexdigest()
            schemas.append(
                RegisteredResearchSchema(
                    manifest_id=f"schema_{digest}",
                    schema_version=document.schema_version,
                    artifact_kind=document.artifact_kind,
                    fields=document.fields,
                )
            )
        return cls(tuple(schemas))

    @property
    def kinds(self) -> tuple[ArtifactKind, ...]:
        """Return registered kinds in deterministic order."""
        return tuple(
            sorted({schema.artifact_kind for schema in self._schemas}, key=lambda kind: kind.value)
        )

    def schemas(self, kind: ArtifactKind) -> tuple[RegisteredResearchSchema, ...]:
        """Return every registered schema for one artifact kind."""
        values = tuple(schema for schema in self._schemas if schema.artifact_kind is kind)
        if not values:
            raise ResearchArtifactError(
                ArtifactRule.SCHEMA_MISMATCH,
                f"artifact kind has no registered row schema: {kind.value}",
            )
        return values

    def schema(
        self,
        kind: ArtifactKind,
        manifest_id: str | None = None,
    ) -> RegisteredResearchSchema:
        """Return an exact schema, rejecting ambiguous kind-only lookup."""
        if manifest_id is not None:
            schema = self._by_id.get(manifest_id)
            if schema is None or schema.artifact_kind is not kind:
                raise ResearchArtifactError(
                    ArtifactRule.SCHEMA_MISMATCH,
                    f"schema is not registered for {kind.value}: {manifest_id}",
                )
            return schema
        values = self.schemas(kind)
        if len(values) != 1:
            raise ResearchArtifactError(
                ArtifactRule.SCHEMA_MISMATCH,
                f"artifact kind requires exact schema identity: {kind.value}",
            )
        return values[0]

    def validate(
        self,
        kind: ArtifactKind,
        frame: pl.DataFrame,
        manifest_id: str | None = None,
    ) -> None:
        """Require exact order, physical types, nullability, and schema identity."""
        schema = self.schema(kind, manifest_id)
        expected = _schema_to_polars(schema)
        if frame.schema != expected:
            raise ResearchArtifactError(
                ArtifactRule.SCHEMA_MISMATCH,
                f"columns or physical types differ for {kind.value}",
            )
        required_with_nulls = tuple(
            field.name
            for field in schema.fields
            if not field.nullable and frame.get_column(field.name).null_count() > 0
        )
        if required_with_nulls:
            raise ResearchArtifactError(
                ArtifactRule.SCHEMA_MISMATCH,
                f"required fields contain nulls: {','.join(required_with_nulls)}",
            )

    def polars_schema(
        self,
        kind: ArtifactKind,
        manifest_id: str | None = None,
    ) -> pl.Schema:
        """Return the exact physical Polars schema for one registered kind."""
        return _schema_to_polars(self.schema(kind, manifest_id))


def _schema_to_polars(schema: RegisteredResearchSchema) -> pl.Schema:
    return pl.Schema({field.name: _polars_type(field.data_type) for field in schema.fields})


def _polars_type(field_type: ResearchFieldType) -> pl.DataType | type[pl.DataType]:
    match field_type:
        case ResearchFieldType.BOOL:
            return pl.Boolean
        case ResearchFieldType.DATETIME_ASIA_SHANGHAI:
            return pl.Datetime("us", "Asia/Shanghai")
        case ResearchFieldType.FLOAT64:
            return pl.Float64
        case ResearchFieldType.LIST_STRING:
            return pl.List(pl.String)
        case ResearchFieldType.STRING:
            return pl.String
