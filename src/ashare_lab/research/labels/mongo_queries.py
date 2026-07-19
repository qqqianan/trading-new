"""Shared exact-schema Mongo queries for label evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ashare_lab.research.features.market.mongo_documents import (
    DailyDocument,
    LimitDocument,
    SuspensionDocument,
)

if TYPE_CHECKING:
    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.research.features.market.mongo_contracts import MarketDatabase


def load_documents[T: DailyDocument | LimitDocument | SuspensionDocument](
    database: MarketDatabase,
    collection: str,
    model: type[T],
    snapshot_ids: tuple[str, ...],
    schema_manifest_id: str,
) -> tuple[T, ...]:
    """Load accepted documents only through exact Raw snapshot identities."""
    if not snapshot_ids:
        return ()
    query: BsonDocument = {
        "schema_manifest_id": schema_manifest_id,
        "quality_status": "ACCEPTED",
        "source_snapshot_id": {"$in": list(snapshot_ids)},
    }
    projection: BsonDocument = {"_id": 0}
    projection.update(dict.fromkeys(model.model_fields, 1))
    return tuple(
        model.model_validate(document) for document in database[collection].find(query, projection)
    )


def snapshot_projection() -> BsonDocument:
    """Return the closed Raw snapshot metadata projection."""
    return {
        "_id": 0,
        "snapshot_id": 1,
        "endpoint": 1,
        "request_params_canonical": 1,
        "schema_manifest_id": 1,
        "status": 1,
    }
