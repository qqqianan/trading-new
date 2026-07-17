"""MongoDB persistence for canonical records, quality evidence, and lineage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from pymongo import MongoClient, UpdateOne

from ashare_lab.code_identity import load_git_commit
from ashare_lab.data.mongo_documents import canonical_document

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch
    from ashare_lab.data.schema_registry import EndpointSchema

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MARKET_ENDPOINTS: Final[frozenset[str]] = frozenset(
    {"daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d"}
)


class _SnapshotEvidence(BaseModel):
    """Accepted Raw snapshot fields needed for resume detection."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    endpoint: str
    request_params_canonical: str


class _TradeDateParams(BaseModel):
    """Typed projection of one daily endpoint request."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    trade_date: str


class _LineageEvidence(BaseModel):
    """Canonical artifact identity derived from one Raw snapshot."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    downstream_artifact_id: str


class _CanonicalIdentity(BaseModel):
    """Stored immutable canonical identity used to avoid redundant upserts."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    record_id: str


@dataclass(frozen=True, slots=True)
class CanonicalWriteResult:
    """Counts and identity produced by one idempotent canonical write."""

    artifact_id: str
    record_count: int
    inserted_count: int
    quality_status: str


class MongoCanonicalStore:
    """Persist canonical artifacts while binding quality and field lineage."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind only the isolated market database."""
        if database_name != "ashare_quant":
            msg = "canonical store is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]

    def write(self, schema: EndpointSchema, batch: CanonicalBatch) -> CanonicalWriteResult:
        """Append records and immutable evidence, returning an idempotent result."""
        inserted = self._write_records(schema, batch, frozenset())
        status = batch.quality_status
        self._write_quality(batch, status)
        self._write_lineage(schema, batch)
        return CanonicalWriteResult(batch.artifact_id, len(batch.records), inserted, status)

    def write_replayed(
        self,
        schema: EndpointSchema,
        batch: CanonicalBatch,
    ) -> CanonicalWriteResult:
        """Append only missing rows before writing current replay evidence."""
        record_ids = [record.record_id for record in batch.records]
        existing = frozenset(
            _CanonicalIdentity.model_validate(document).record_id
            for document in self._database[schema.canonical_collection].find(
                {"_id": {"$in": record_ids}},
                {"_id": 0, "record_id": 1},
            )
        )
        inserted = self._write_records(schema, batch, existing)
        status = batch.quality_status
        self._write_quality(batch, status)
        self._write_lineage(schema, batch)
        return CanonicalWriteResult(batch.artifact_id, len(batch.records), inserted, status)

    def _write_records(
        self,
        schema: EndpointSchema,
        batch: CanonicalBatch,
        existing: frozenset[str],
    ) -> int:
        collection = self._database[schema.canonical_collection]
        operations = [
            UpdateOne(
                {"_id": record.record_id},
                {"$setOnInsert": canonical_document(record)},
                upsert=True,
            )
            for record in batch.records
            if record.record_id not in existing
        ]
        return collection.bulk_write(operations, ordered=False).upserted_count if operations else 0

    def completed_market_dates(
        self,
        schema_manifest_id: str,
        start_date: str,
        end_date: str,
    ) -> frozenset[str]:
        """Return dates with accepted Raw, canonical lineage, and quality for all endpoints."""
        completed_endpoints: dict[str, set[str]] = {}
        snapshots = self._database["meta_source_snapshots"].find(
            {
                "endpoint": {"$in": sorted(_MARKET_ENDPOINTS)},
                "schema_manifest_id": schema_manifest_id,
                "status": "ACCEPTED",
            }
        )
        for document in snapshots:
            snapshot = _SnapshotEvidence.model_validate(document)
            params = _TradeDateParams.model_validate_json(snapshot.request_params_canonical)
            if not start_date <= params.trade_date <= end_date:
                continue
            lineage_document = self._database["meta_lineage_edges"].find_one(
                {
                    "upstream_artifact_id": snapshot.snapshot_id,
                    "output_schema_id": schema_manifest_id,
                }
            )
            if lineage_document is None:
                continue
            lineage = _LineageEvidence.model_validate(lineage_document)
            quality = self._database["meta_quality_reports"].find_one(
                {"artifact_id": lineage.downstream_artifact_id, "passed": True},
                {"_id": 1},
            )
            if quality is not None:
                completed_endpoints.setdefault(params.trade_date, set()).add(snapshot.endpoint)
        return frozenset(
            trade_date
            for trade_date, endpoints in completed_endpoints.items()
            if endpoints == set(_MARKET_ENDPOINTS)
        )

    def _write_quality(self, batch: CanonicalBatch, status: str) -> None:
        report_id = (
            batch.records[0].quality_report_id if batch.records else _empty_quality_id(batch)
        )
        passed = status == "ACCEPTED"
        self._database["meta_quality_reports"].update_one(
            {"_id": report_id},
            {
                "$setOnInsert": {
                    "_id": report_id,
                    "quality_report_id": report_id,
                    "artifact_id": batch.artifact_id,
                    "rulebook_version": "1.1.0",
                    "checks": ["canonical_schema", "pit_time_policy", "field_lineage"],
                    "passed": passed,
                    "failure_codes": [] if passed else ["not_historical_pit"],
                    "checked_at": datetime.now(_SHANGHAI),
                }
            },
            upsert=True,
        )

    def _write_lineage(self, schema: EndpointSchema, batch: CanonicalBatch) -> None:
        code_commit = load_git_commit(Path.cwd())
        identity = f"{batch.artifact_id}|{code_commit}"
        edge_id = f"lineage_{hashlib.sha256(identity.encode()).hexdigest()}"
        parameters = hashlib.sha256(schema.available_at_policy.encode()).hexdigest()
        self._database["meta_lineage_edges"].update_one(
            {"_id": edge_id},
            {
                "$setOnInsert": {
                    "_id": edge_id,
                    "lineage_edge_id": edge_id,
                    "upstream_artifact_id": batch.source_snapshot_id,
                    "downstream_artifact_id": batch.artifact_id,
                    "transform_name": batch.transform_name,
                    "transform_version": batch.transform_version,
                    "code_commit": code_commit,
                    "input_schema_ids": [batch.schema_manifest_id],
                    "output_schema_id": batch.schema_manifest_id,
                    "parameters_sha256": parameters,
                    "field_mappings": list(batch.field_mappings),
                    "executed_at": datetime.now(_SHANGHAI),
                }
            },
            upsert=True,
        )


def _empty_quality_id(batch: CanonicalBatch) -> str:
    digest = hashlib.sha256(batch.artifact_id.encode()).hexdigest()
    return f"quality_canonical_{digest}"
