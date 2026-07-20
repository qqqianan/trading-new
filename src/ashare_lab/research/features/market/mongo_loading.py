"""Exact snapshot and symbol-bounded loading of canonical market rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ashare_lab.research.features.market.mongo_documents import CanonicalDocument

if TYPE_CHECKING:
    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.research.features.market.mongo_contracts import MarketDatabase


@dataclass(frozen=True, slots=True)
class MarketLoadBoundary:
    """Exact Raw snapshots, schema, and optional symbol filter for one chain."""

    snapshot_ids: tuple[str, ...]
    schema_manifest_id: str
    symbols: tuple[str, ...] | None


def load_market_documents[T: CanonicalDocument](
    database: MarketDatabase,
    collection: str,
    model: type[T],
    boundary: MarketLoadBoundary,
) -> tuple[T, ...]:
    """Load accepted rows through exact Raw snapshots and optional symbols."""
    if not boundary.snapshot_ids:
        return ()
    query: BsonDocument = {
        "schema_manifest_id": boundary.schema_manifest_id,
        "quality_status": "ACCEPTED",
        "source_snapshot_id": {"$in": list(boundary.snapshot_ids)},
    }
    if boundary.symbols is not None:
        query["ts_code"] = {"$in": list(boundary.symbols)}
    projection: BsonDocument = {"_id": 0}
    projection.update(dict.fromkeys(model.model_fields, 1))
    return tuple(
        model.model_validate(document) for document in database[collection].find(query, projection)
    )
