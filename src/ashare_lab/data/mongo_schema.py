"""Build strict MongoDB validators from the committed schema registry."""

from dataclasses import dataclass
from typing import Final

from ashare_lab.data.schema_registry import (
    EndpointSchema,
    FieldSpec,
    FieldType,
    GovernanceSchema,
    SchemaRegistry,
)

_BSON_TYPES: Final[dict[FieldType, tuple[str, ...]]] = {
    FieldType.ARRAY_STRING: ("array",),
    FieldType.BOOL: ("bool",),
    FieldType.DATE_YYYYMMDD: ("string",),
    FieldType.DATETIME: ("date",),
    FieldType.DOCUMENT: ("object",),
    FieldType.FLOAT: ("double", "int", "long", "decimal"),
    FieldType.INT: ("int", "long"),
    FieldType.STRING: ("string",),
}


@dataclass(frozen=True, slots=True)
class MongoRule:
    """Typed recursive representation of one MongoDB JSON Schema rule."""

    bson_types: tuple[str, ...]
    required: tuple[str, ...] = ()
    additional_properties: bool | None = None
    properties: tuple[tuple[str, "MongoRule"], ...] = ()
    items: "MongoRule | None" = None

    def property(self, name: str) -> "MongoRule":
        """Return a named child rule, failing closed for undocumented fields."""
        for property_name, rule in self.properties:
            if property_name == name:
                return rule
        msg = f"Mongo schema property is not documented: {name}"
        raise KeyError(msg)


@dataclass(frozen=True, slots=True)
class MongoValidator:
    """Top-level validator associated with one MongoDB collection."""

    root: MongoRule


class MongoSchemaBuilder:
    """Translate registry field contracts into closed MongoDB JSON schemas."""

    def __init__(self, registry: SchemaRegistry) -> None:
        """Bind the committed registry used to generate every validator."""
        self._registry = registry

    def collection_plan(self) -> dict[str, MongoValidator]:
        """Return every governance, Raw, and canonical collection validator."""
        plan = {
            name: self.governance_validator(schema)
            for name, schema in self._registry.governance_collections.items()
        }
        plan.update(
            {
                name: self.governance_validator(schema)
                for name, schema in self._registry.managed_collections.items()
            }
        )
        for endpoint_name in self._registry.endpoint_names:
            endpoint = self._registry.endpoint(endpoint_name)
            plan[endpoint.raw_collection] = self.raw_validator(endpoint)
            plan[endpoint.canonical_collection] = self.canonical_validator(endpoint)
        return plan

    def raw_validator(self, endpoint: EndpointSchema) -> MongoValidator:
        """Require the immutable Raw envelope and exact provider payload fields."""
        envelope = _closed_object(self._registry.raw_envelope)
        payload = _closed_object(endpoint.fields)
        properties = tuple(
            (name, payload if name == "payload" else rule) for name, rule in envelope.properties
        )
        return MongoValidator(
            MongoRule(
                bson_types=envelope.bson_types,
                required=envelope.required,
                additional_properties=False,
                properties=properties,
            )
        )

    def canonical_validator(self, endpoint: EndpointSchema) -> MongoValidator:
        """Require canonical lineage fields and normalized business fields."""
        combined = self._registry.canonical_envelope + endpoint.fields
        return MongoValidator(_closed_object(combined))

    @staticmethod
    def governance_validator(schema: GovernanceSchema) -> MongoValidator:
        """Require every documented governance field and reject unknown fields."""
        return MongoValidator(_closed_object(schema.fields))


def _closed_object(fields: tuple[FieldSpec, ...]) -> MongoRule:
    required = tuple(name for name, _, nullable, _, _, _ in fields if not nullable)
    properties = tuple((field[0], _field_rule(field)) for field in fields)
    return MongoRule(
        bson_types=("object",),
        required=required,
        additional_properties=False,
        properties=properties,
    )


def _field_rule(field: FieldSpec) -> MongoRule:
    _, field_type, nullable, _, _, _ = field
    bson_types = _BSON_TYPES[field_type] + (("null",) if nullable else ())
    items = MongoRule(("string",)) if field_type is FieldType.ARRAY_STRING else None
    return MongoRule(bson_types=bson_types, items=items)
