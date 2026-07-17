"""Mongo indexes owned by the industry PIT collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo import ASCENDING

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument


def create_industry_indexes(database: Database[BsonDocument], collection_name: str) -> None:
    """Create identities and point-in-time membership lookup indexes."""
    if collection_name != "pit_industry_memberships":
        return
    collection = database[collection_name]
    collection.create_index("membership_id", unique=True, name="membership_id_unique")
    collection.create_index(
        [
            ("schema_manifest_id", ASCENDING),
            ("index_code", ASCENDING),
            ("con_code", ASCENDING),
            ("available_at", ASCENDING),
            ("effective_from", ASCENDING),
            ("effective_to", ASCENDING),
            ("quality_status", ASCENDING),
        ],
        name="pit_industry_membership_lookup",
    )
