"""Read-only Mongo adapter for accepted immutable Raw replay."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from ashare_lab.data.raw_replay import RawReplayError, RawReplayRule, build_stored_snapshot_batch

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.schema_registry import SchemaRegistry
    from ashare_lab.data.snapshots import SnapshotBatch


class _SnapshotIdDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str


class MongoRawReplayReader:
    """Load complete Raw batches without changing source collections."""

    def __init__(self, database: Database[BsonDocument]) -> None:
        """Bind only to the governed isolated database."""
        if database.name != "ashare_quant":
            raise RawReplayError(
                RawReplayRule.DATABASE_ISOLATION,
                f"Raw replay requires ashare_quant, got {database.name}",
            )
        self._database = database

    def accepted_snapshot_ids(
        self,
        registry: SchemaRegistry,
        endpoints: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return exact current-schema snapshots in stable endpoint/time order."""
        documents = self._database["meta_source_snapshots"].find(
            {
                "schema_manifest_id": registry.manifest_id,
                "status": "ACCEPTED",
                "endpoint": {"$in": list(endpoints)},
            },
            {"_id": 0, "snapshot_id": 1},
            sort=[("endpoint", 1), ("completed_at", 1), ("snapshot_id", 1)],
        )
        return tuple(_SnapshotIdDocument.model_validate(item).snapshot_id for item in documents)

    def load_batch(self, registry: SchemaRegistry, snapshot_id: str) -> SnapshotBatch:
        """Load one manifest and all rows through the strict replay parser."""
        snapshot = self._database["meta_source_snapshots"].find_one(
            {
                "snapshot_id": snapshot_id,
                "schema_manifest_id": registry.manifest_id,
                "status": "ACCEPTED",
            }
        )
        if snapshot is None:
            raise RawReplayError(
                RawReplayRule.SNAPSHOT_MISSING,
                f"accepted snapshot not found: {snapshot_id}",
            )
        endpoint_value = snapshot.get("endpoint")
        if not isinstance(endpoint_value, str):
            raise RawReplayError(
                RawReplayRule.FIELD_CONTRACT_MISMATCH,
                f"snapshot endpoint is invalid: {snapshot_id}",
            )
        schema = registry.endpoint(endpoint_value)
        rows = tuple(
            self._database[schema.raw_collection].find(
                {"snapshot_id": snapshot_id},
                sort=[("row_ordinal", 1)],
            )
        )
        return build_stored_snapshot_batch(snapshot, rows, schema)
