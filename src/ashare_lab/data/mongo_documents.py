"""Pure serialization boundary for MongoDB validators and Raw documents."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import JsonValue

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalRecord
    from ashare_lab.data.mongo_schema import MongoRule, MongoValidator
    from ashare_lab.data.snapshots import RawRow, SourceSnapshot


def validator_document(validator: "MongoValidator") -> dict[str, "JsonValue"]:
    """Serialize a typed Mongo validator into its command document."""
    return {"$jsonSchema": _rule_document(validator.root)}


def snapshot_document(snapshot: "SourceSnapshot") -> "BsonDocument":
    """Serialize one immutable source snapshot manifest."""
    return {
        "_id": snapshot.snapshot_id,
        "snapshot_id": snapshot.snapshot_id,
        "source": snapshot.source,
        "endpoint": snapshot.endpoint,
        "request_params_canonical": snapshot.request_params_canonical,
        "requested_at": snapshot.requested_at,
        "completed_at": snapshot.completed_at,
        "provider_version": snapshot.provider_version,
        "row_count": snapshot.row_count,
        "payload_sha256": snapshot.payload_sha256,
        "schema_manifest_id": snapshot.schema_manifest_id,
        "status": snapshot.status,
    }


def raw_document(row: "RawRow") -> "BsonDocument":
    """Serialize one provider row without changing provider field names or values."""
    return {
        "_id": f"{row.snapshot_id}:{row.row_ordinal}",
        "snapshot_id": row.snapshot_id,
        "row_ordinal": row.row_ordinal,
        "ingested_at": row.ingested_at,
        "row_sha256": row.row_sha256,
        "payload": dict(row.payload),
    }


def canonical_document(record: "CanonicalRecord") -> "BsonDocument":
    """Serialize one canonical record with its normalized business fields."""
    document: BsonDocument = {
        "_id": record.record_id,
        "record_id": record.record_id,
        "schema_manifest_id": record.schema_manifest_id,
        "source_snapshot_id": record.source_snapshot_id,
        "source_row_sha256": record.source_row_sha256,
        "transform_name": record.transform_name,
        "transform_version": record.transform_version,
        "event_time": record.event_time,
        "available_at": record.available_at,
        "ingested_at": record.ingested_at,
        "quality_status": record.quality_status,
        "quality_report_id": record.quality_report_id,
    }
    document.update(dict(record.business_fields))
    return document


def _rule_document(rule: "MongoRule") -> dict[str, "JsonValue"]:
    bson_type: JsonValue = (
        rule.bson_types[0] if len(rule.bson_types) == 1 else list(rule.bson_types)
    )
    document: dict[str, JsonValue] = {"bsonType": bson_type}
    if rule.required:
        document["required"] = list(rule.required)
    if rule.additional_properties is not None:
        document["additionalProperties"] = rule.additional_properties
    if rule.properties:
        document["properties"] = {name: _rule_document(child) for name, child in rule.properties}
    if rule.items is not None:
        document["items"] = _rule_document(rule.items)
    return document
