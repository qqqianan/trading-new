"""Project governed industry member snapshots into observed-at PIT intervals."""

from dataclasses import dataclass

from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.config import DataSettings
from ashare_lab.data.industry_memberships import (
    build_industry_membership,
    validate_industry_membership_batch,
)
from ashare_lab.data.industry_store import MongoIndustryStore
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.sync_service import SyncResult


@dataclass(frozen=True, slots=True)
class IndustryPipelineResult:
    """Aggregate counts from exact industry membership batches."""

    batch_count: int
    event_count: int
    inserted_count: int


def persist_industry_results(
    registry: SchemaRegistry,
    results: tuple[SyncResult, ...],
) -> IndustryPipelineResult:
    """Validate and persist observed-at memberships plus empty evidence."""
    settings = DataSettings()
    event_count = inserted_count = 0
    with MongoClient[BsonDocument](settings.mongodb_uri, serverSelectionTimeoutMS=8_000) as mongo:
        store = MongoIndustryStore(mongo, settings.mongodb_database)
        for result in results:
            if result.batch.snapshot.endpoint != "index_member":
                detail = f"unsupported industry endpoint: {result.batch.snapshot.endpoint}"
                raise SchemaContractError(detail)
            schema = registry.endpoint("index_member")
            canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
            validate_industry_membership_batch(canonical)
            events = tuple(build_industry_membership(record) for record in canonical.records)
            written = store.write_batch(canonical, events)
            event_count += written.event_count
            inserted_count += written.inserted_count
    return IndustryPipelineResult(len(results), event_count, inserted_count)
