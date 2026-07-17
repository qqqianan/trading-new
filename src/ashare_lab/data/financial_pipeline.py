"""Orchestrate governed income batches into PIT version evidence."""

from dataclasses import dataclass

from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.config import DataSettings
from ashare_lab.data.financial_store import MongoFinancialEventStore
from ashare_lab.data.financials import build_income_version
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.sync_service import SyncResult


@dataclass(frozen=True, slots=True)
class FinancialPipelineResult:
    """Aggregate counts from a bounded income PIT projection."""

    batch_count: int
    event_count: int
    inserted_count: int


def persist_income_results(
    registry: SchemaRegistry,
    results: tuple[SyncResult, ...],
) -> FinancialPipelineResult:
    """Project income responses and persist versions plus empty-period evidence."""
    settings = DataSettings()
    event_count = 0
    inserted_count = 0
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        store = MongoFinancialEventStore(mongo, settings.mongodb_database)
        for result in results:
            endpoint = result.batch.snapshot.endpoint
            if endpoint not in {"income", "income_vip"}:
                detail = f"unsupported financial source endpoint: {endpoint}"
                raise SchemaContractError(detail)
            schema = registry.endpoint(endpoint)
            canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
            events = tuple(build_income_version(record, endpoint) for record in canonical.records)
            written = store.write_batch(canonical, events)
            event_count += written.event_count
            inserted_count += written.inserted_count
    return FinancialPipelineResult(len(results), event_count, inserted_count)
