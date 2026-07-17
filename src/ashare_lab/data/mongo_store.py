"""Append-only MongoDB storage for accepted Tushare Raw snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pymongo import ASCENDING, MongoClient, UpdateOne
from pymongo.errors import BulkWriteError

from ashare_lab.data.benchmark_indexes import create_benchmark_indexes
from ashare_lab.data.financial_indicator_indexes import create_financial_indicator_indexes
from ashare_lab.data.industry_indexes import create_industry_indexes
from ashare_lab.data.mongo_documents import raw_document, snapshot_document, validator_document
from ashare_lab.data.mongo_errors import RawPersistenceError
from ashare_lab.data.mongo_registry import register_schema
from ashare_lab.data.mongo_schema import MongoSchemaBuilder

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.schema_registry import EndpointSchema, SchemaRegistry
    from ashare_lab.data.snapshots import SnapshotBatch

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class StoredSnapshot:
    """Observable outcome of one idempotent Raw write."""

    snapshot_id: str
    row_count: int
    inserted: bool


class MongoRawStore:
    """Own collection initialization and immutable Raw writes."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind a client while enforcing the isolated database name."""
        if database_name != "ashare_quant":
            msg = "market data store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def initialize(self, registry: SchemaRegistry) -> tuple[str, ...]:
        """Create or tighten every collection without dropping existing data."""
        plan = MongoSchemaBuilder(registry).collection_plan()
        existing = set(self._database.list_collection_names())
        for name, validator in plan.items():
            document = validator_document(validator)
            if name in existing:
                self._database.command(
                    "collMod",
                    name,
                    validator=document,
                    validationLevel="strict",
                    validationAction="error",
                )
            else:
                self._database.create_collection(
                    name,
                    validator=document,
                    validationLevel="strict",
                    validationAction="error",
                )
            self._create_indexes(name)
        register_schema(self._database, registry, tuple(sorted(plan)))
        return tuple(sorted(plan))

    def write_batch(self, schema: EndpointSchema, batch: SnapshotBatch) -> StoredSnapshot:
        """Insert an exact response once and persist its schema quality evidence."""
        snapshots = self._database["meta_source_snapshots"]
        snapshot_id = batch.snapshot.snapshot_id
        raw_collection = self._database[schema.raw_collection]
        stored_rows = raw_collection.count_documents({"snapshot_id": snapshot_id})
        existing = snapshots.find_one({"_id": snapshot_id}, {"_id": 1, "status": 1})
        if (
            existing is not None
            and existing.get("status") == "ACCEPTED"
            and stored_rows == len(batch.rows)
        ):
            return StoredSnapshot(snapshot_id, batch.snapshot.row_count, inserted=False)

        if existing is None:
            snapshots.insert_one(snapshot_document(batch.snapshot))
        if batch.rows:
            try:
                raw_collection.bulk_write(
                    [
                        UpdateOne(
                            {"_id": f"{row.snapshot_id}:{row.row_ordinal}"},
                            {"$setOnInsert": raw_document(row)},
                            upsert=True,
                        )
                        for row in batch.rows
                    ],
                    ordered=False,
                )
            except BulkWriteError as error:
                self._record_rejection(snapshot_id)
                raise RawPersistenceError(snapshot_id) from error
        quality_id = f"quality_{hashlib.sha256(snapshot_id.encode()).hexdigest()}"
        self._database["meta_quality_reports"].update_one(
            {"_id": quality_id},
            {
                "$setOnInsert": {
                    "_id": quality_id,
                    "quality_report_id": quality_id,
                    "artifact_id": snapshot_id,
                    "rulebook_version": "1.1.0",
                    "checks": ["committed_field_contract", "row_width", "content_hash"],
                    "passed": True,
                    "failure_codes": [],
                    "checked_at": datetime.now(_SHANGHAI),
                }
            },
            upsert=True,
        )
        snapshots.update_one({"_id": snapshot_id}, {"$set": {"status": "ACCEPTED"}})
        return StoredSnapshot(snapshot_id, batch.snapshot.row_count, inserted=True)

    def _record_rejection(self, snapshot_id: str) -> None:
        rejected_id = f"quality_reject_{hashlib.sha256(snapshot_id.encode()).hexdigest()}"
        self._database["meta_quality_reports"].update_one(
            {"_id": rejected_id},
            {
                "$setOnInsert": {
                    "_id": rejected_id,
                    "quality_report_id": rejected_id,
                    "artifact_id": snapshot_id,
                    "rulebook_version": "1.1.0",
                    "checks": ["mongo_json_schema"],
                    "passed": False,
                    "failure_codes": ["mongo_schema_validation"],
                    "checked_at": datetime.now(_SHANGHAI),
                }
            },
            upsert=True,
        )
        self._database["meta_source_snapshots"].update_one(
            {"_id": snapshot_id},
            {"$set": {"status": "REJECTED"}},
        )

    def _create_indexes(self, name: str) -> None:
        collection = self._database[name]
        create_benchmark_indexes(self._database, name)
        create_financial_indicator_indexes(self._database, name)
        create_industry_indexes(self._database, name)
        if name.startswith("raw_tushare_"):
            collection.create_index(
                [("snapshot_id", ASCENDING), ("row_ordinal", ASCENDING)],
                unique=True,
                name="snapshot_row_unique",
            )
            collection.create_index("row_sha256", name="row_sha256")
        if name.startswith("canonical_"):
            collection.create_index("record_id", unique=True, name="record_id_unique")
            collection.create_index("source_snapshot_id", name="source_snapshot_id")
        if name == "pit_security_events":
            collection.create_index("event_id", unique=True, name="event_id_unique")
            collection.create_index(
                [
                    ("schema_manifest_id", ASCENDING),
                    ("ts_code", ASCENDING),
                    ("effective_at", ASCENDING),
                    ("available_at", ASCENDING),
                    ("quality_status", ASCENDING),
                ],
                name="pit_state_lookup",
            )
        if name == "pit_dividend_events":
            collection.create_index("event_id", unique=True, name="event_id_unique")
            collection.create_index(
                [
                    ("schema_manifest_id", ASCENDING),
                    ("ts_code", ASCENDING),
                    ("effective_at", ASCENDING),
                    ("available_at", ASCENDING),
                    ("quality_status", ASCENDING),
                ],
                name="pit_dividend_lookup",
            )
        if name == "pit_income_statements":
            collection.create_index("event_id", unique=True, name="event_id_unique")
            collection.create_index(
                [
                    ("schema_manifest_id", ASCENDING),
                    ("ts_code", ASCENDING),
                    ("end_date", ASCENDING),
                    ("effective_at", ASCENDING),
                    ("available_at", ASCENDING),
                    ("quality_status", ASCENDING),
                ],
                name="pit_income_lookup",
            )
        if name == "pit_balance_sheets":
            collection.create_index("event_id", unique=True, name="event_id_unique")
            collection.create_index(
                [
                    ("schema_manifest_id", ASCENDING),
                    ("ts_code", ASCENDING),
                    ("end_date", ASCENDING),
                    ("effective_at", ASCENDING),
                    ("available_at", ASCENDING),
                    ("quality_status", ASCENDING),
                ],
                name="pit_balance_sheet_lookup",
            )
        if name == "pit_cashflow_statements":
            collection.create_index("event_id", unique=True, name="event_id_unique")
            collection.create_index(
                [
                    ("schema_manifest_id", ASCENDING),
                    ("ts_code", ASCENDING),
                    ("end_date", ASCENDING),
                    ("available_at", ASCENDING),
                    ("quality_status", ASCENDING),
                ],
                name="pit_cashflow_lookup",
            )
        if name == "meta_lineage_edges":
            collection.create_index(
                [("upstream_artifact_id", ASCENDING), ("output_schema_id", ASCENDING)],
                name="lineage_upstream_output",
            )
            collection.create_index(
                [("downstream_artifact_id", ASCENDING), ("output_schema_id", ASCENDING)],
                name="lineage_downstream_output",
            )
        if name == "meta_quality_reports":
            collection.create_index(
                [("artifact_id", ASCENDING), ("passed", ASCENDING)],
                name="quality_artifact_passed",
            )
