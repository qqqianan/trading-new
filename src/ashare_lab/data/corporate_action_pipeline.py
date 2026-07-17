"""Orchestrate governed dividend batches into PIT event evidence."""

from dataclasses import dataclass

from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.config import DataSettings
from ashare_lab.data.corporate_action_store import MongoDividendEventStore
from ashare_lab.data.corporate_actions import build_dividend_events
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.sync_service import SyncResult


@dataclass(frozen=True, slots=True)
class DividendPipelineResult:
    """Aggregate counts from a bounded dividend PIT projection."""

    batch_count: int
    event_count: int
    inserted_count: int


def persist_dividend_results(
    registry: SchemaRegistry,
    results: tuple[SyncResult, ...],
) -> DividendPipelineResult:
    """Project dividend results and persist events plus empty-batch evidence."""
    settings = DataSettings()
    event_count = 0
    inserted_count = 0
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        store = MongoDividendEventStore(mongo, settings.mongodb_database)
        for result in results:
            endpoint = result.batch.snapshot.endpoint
            if endpoint != "dividend":
                detail = f"unsupported corporate-action source endpoint: {endpoint}"
                raise SchemaContractError(detail)
            schema = registry.endpoint(endpoint)
            canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
            events = tuple(
                event for record in canonical.records for event in build_dividend_events(record)
            )
            written = store.write_batch(canonical, events)
            event_count += written.event_count
            inserted_count += written.inserted_count
    return DividendPipelineResult(len(results), event_count, inserted_count)
