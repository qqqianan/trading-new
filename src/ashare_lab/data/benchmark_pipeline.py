"""Orchestrate governed index-weight batches into PIT evidence."""

from dataclasses import dataclass

from pymongo import MongoClient

from ashare_lab.data.benchmark_store import MongoBenchmarkWeightStore
from ashare_lab.data.benchmark_weights import (
    build_index_weight_event,
    validate_index_weight_batch,
)
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.sync_service import SyncResult


@dataclass(frozen=True, slots=True)
class BenchmarkPipelineResult:
    """Aggregate counts from bounded index-weight PIT projections."""

    batch_count: int
    event_count: int
    inserted_count: int


def persist_benchmark_weight_results(
    registry: SchemaRegistry, results: tuple[SyncResult, ...]
) -> BenchmarkPipelineResult:
    """Validate monthly weights and persist events plus empty-month evidence."""
    settings = DataSettings()
    event_count = inserted_count = 0
    with MongoClient[BsonDocument](settings.mongodb_uri, serverSelectionTimeoutMS=8_000) as mongo:
        store = MongoBenchmarkWeightStore(mongo, settings.mongodb_database)
        for result in results:
            if result.batch.snapshot.endpoint != "index_weight":
                detail = f"unsupported benchmark endpoint: {result.batch.snapshot.endpoint}"
                raise SchemaContractError(detail)
            schema = registry.endpoint("index_weight")
            canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
            validate_index_weight_batch(canonical)
            events = tuple(build_index_weight_event(record) for record in canonical.records)
            written = store.write_batch(canonical, events)
            event_count += written.event_count
            inserted_count += written.inserted_count
    return BenchmarkPipelineResult(len(results), event_count, inserted_count)
