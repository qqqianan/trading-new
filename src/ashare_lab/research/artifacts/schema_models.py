"""Typed contracts for committed research row schemas."""

from enum import StrEnum, unique

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.research.artifacts.models import ArtifactKind


@unique
class ResearchFieldType(StrEnum):
    """Closed physical types allowed in research Parquet rows."""

    BOOL = "bool"
    DATETIME_ASIA_SHANGHAI = "datetime_asia_shanghai"
    FLOAT64 = "float64"
    LIST_STRING = "list_string"
    STRING = "string"


class ResearchFieldSchema(BaseModel):
    """Physical and semantic documentation for one research column."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    data_type: ResearchFieldType
    nullable: bool
    unit: str = Field(min_length=1)
    null_semantics: str = Field(min_length=1)
    time_role: str = Field(min_length=1)
    allowed_use: str = Field(min_length=1)


class ResearchRowSchemaDocument(BaseModel):
    """One versioned exact-column contract for a materialized row kind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    artifact_kind: ArtifactKind
    fields: tuple[ResearchFieldSchema, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def fields_are_unique(self) -> "ResearchRowSchemaDocument":
        """Reject ambiguous column contracts at the trust boundary."""
        names = tuple(field.name for field in self.fields)
        if len(names) != len(set(names)):
            detail = "research row field names must be unique"
            raise ValueError(detail)
        return self
