"""Typed loader for committed market-data schema bundles."""

import hashlib
from enum import StrEnum, unique
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


@unique
class FieldType(StrEnum):
    """Storage types allowed by the first schema registry version."""

    ARRAY_STRING = "array_string"
    BOOL = "bool"
    DATE_YYYYMMDD = "date_yyyymmdd"
    DATETIME = "datetime"
    DOCUMENT = "document"
    FLOAT = "float"
    INT = "int"
    STRING = "string"


FieldSpec = tuple[str, FieldType, bool, str, str, str]


class EndpointSchema(BaseModel):
    """Complete source and storage contract for one Tushare endpoint."""

    model_config = ConfigDict(frozen=True)

    raw_collection: str = Field(min_length=1)
    canonical_collection: str = Field(min_length=1)
    natural_key: tuple[str, ...] = Field(min_length=1)
    event_time_field: str = Field(min_length=1)
    available_at_policy: str = Field(min_length=1)
    fields: tuple[FieldSpec, ...] = Field(min_length=1)

    @property
    def field_names(self) -> tuple[str, ...]:
        """Return provider fields in the committed request order."""
        return tuple(field[0] for field in self.fields)


class GovernanceSchema(BaseModel):
    """Field contract for one governance collection."""

    model_config = ConfigDict(frozen=True)

    natural_key: tuple[str, ...] = Field(min_length=1)
    fields: tuple[FieldSpec, ...] = Field(min_length=1)


class SchemaBundle(BaseModel):
    """Validated root of the P0 schema registry document."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(min_length=1)
    database: str = Field(min_length=1)
    source: str = Field(min_length=1)
    field_tuple: tuple[str, ...]
    raw_envelope: tuple[FieldSpec, ...]
    canonical_envelope: tuple[FieldSpec, ...]
    governance_collections: dict[str, GovernanceSchema]
    managed_collections: dict[str, GovernanceSchema] = Field(default_factory=dict)
    endpoints: dict[str, EndpointSchema]


class SchemaContractError(Exception):
    """Provider data or a schema lookup violates the committed contract."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a schema failure with a stable audit detail."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the concrete schema contract failure."""
        return self.detail


class SchemaRegistry:
    """Immutable schema bundle with a content-addressed identity."""

    def __init__(self, bundle: SchemaBundle, manifest_id: str) -> None:
        """Bind a validated bundle to its exact file hash."""
        self._bundle = bundle
        self._manifest_id = manifest_id

    @classmethod
    def load(cls, path: Path) -> "SchemaRegistry":
        """Parse and hash one committed schema bundle."""
        content = path.read_bytes()
        bundle = SchemaBundle.model_validate_json(content)
        digest = hashlib.sha256(content).hexdigest()
        return cls(bundle, f"schema_{digest}")

    @property
    def manifest_id(self) -> str:
        """Return the content-addressed schema identity."""
        return self._manifest_id

    @property
    def database(self) -> str:
        """Return the only database accepted by this registry."""
        return self._bundle.database

    @property
    def schema_version(self) -> str:
        """Return the human-readable schema release version."""
        return self._bundle.schema_version

    @property
    def endpoint_names(self) -> tuple[str, ...]:
        """Return registered endpoints in deterministic order."""
        return tuple(sorted(self._bundle.endpoints))

    @property
    def raw_envelope(self) -> tuple[FieldSpec, ...]:
        """Return fields shared by all Raw documents."""
        return self._bundle.raw_envelope

    @property
    def canonical_envelope(self) -> tuple[FieldSpec, ...]:
        """Return fields shared by all canonical documents."""
        return self._bundle.canonical_envelope

    @property
    def governance_collections(self) -> dict[str, GovernanceSchema]:
        """Return an isolated copy of governance collection contracts."""
        return dict(self._bundle.governance_collections)

    @property
    def managed_collections(self) -> dict[str, GovernanceSchema]:
        """Return versioned derived collections owned by this schema bundle."""
        return dict(self._bundle.managed_collections)

    def endpoint(self, name: str) -> EndpointSchema:
        """Return an endpoint or fail closed for an unregistered source."""
        try:
            return self._bundle.endpoints[name]
        except KeyError:
            detail = f"endpoint is not registered in schema bundle: {name}"
            raise SchemaContractError(detail) from None
