"""Orchestrate governed financial indicators into PIT evidence."""

from dataclasses import dataclass

from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.config import DataSettings
from ashare_lab.data.financial_indicator_store import MongoFinancialIndicatorStore
from ashare_lab.data.financial_indicators import build_financial_indicator_version
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.sync_service import SyncResult


@dataclass(frozen=True, slots=True)
class IndicatorPipelineResult:
    """Aggregate counts from a bounded indicator PIT projection."""

    batch_count: int
    event_count: int
    inserted_count: int


def persist_financial_indicator_results(
    registry: SchemaRegistry, results: tuple[SyncResult, ...]
) -> IndicatorPipelineResult:
    """Project governed responses and persist PIT plus empty-batch evidence."""
    settings = DataSettings()
    event_count = inserted_count = 0
    with MongoClient[BsonDocument](settings.mongodb_uri, serverSelectionTimeoutMS=8_000) as mongo:
        store = MongoFinancialIndicatorStore(mongo, settings.mongodb_database)
        for result in results:
            if result.batch.snapshot.endpoint != "fina_indicator":
                detail = (
                    f"unsupported financial-indicator endpoint: {result.batch.snapshot.endpoint}"
                )
                raise SchemaContractError(detail)
            schema = registry.endpoint("fina_indicator")
            canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
            events = tuple(build_financial_indicator_version(r) for r in canonical.records)
            written = store.write_batch(canonical, events)
            event_count += written.event_count
            inserted_count += written.inserted_count
    return IndicatorPipelineResult(len(results), event_count, inserted_count)
