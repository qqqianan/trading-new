"""Register immutable schema manifests in the governed Mongo database."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.schema_registry import SchemaRegistry

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def register_schema(
    database: Database[BsonDocument],
    registry: SchemaRegistry,
    collections: tuple[str, ...],
) -> None:
    """Append one content-addressed schema manifest when first observed."""
    manifests = database["meta_schema_manifests"]
    if manifests.find_one({"_id": registry.manifest_id}, {"_id": 1}) is not None:
        return
    manifests.insert_one(
        {
            "_id": registry.manifest_id,
            "schema_manifest_id": registry.manifest_id,
            "schema_version": registry.schema_version,
            "bundle_sha256": registry.manifest_id.removeprefix("schema_"),
            "database": registry.database,
            "collections": list(collections),
            "registered_at": datetime.now(_SHANGHAI),
        }
    )
