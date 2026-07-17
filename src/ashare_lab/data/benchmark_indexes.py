"""Mongo indexes owned by the benchmark schema."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo import ASCENDING

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument


def create_benchmark_indexes(database: Database[BsonDocument], collection_name: str) -> None:
    """Create benchmark indexes only for the owned PIT collection."""
    if collection_name != "pit_index_weights":
        return
    collection = database[collection_name]
    collection.create_index("event_id", unique=True, name="event_id_unique")
    collection.create_index(
        [
            ("schema_manifest_id", ASCENDING),
            ("index_code", ASCENDING),
            ("trade_date", ASCENDING),
            ("available_at", ASCENDING),
            ("quality_status", ASCENDING),
        ],
        name="pit_index_weight_lookup",
    )
