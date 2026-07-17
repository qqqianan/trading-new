"""Orchestrate governed balance-sheet batches into PIT evidence."""

from dataclasses import dataclass

from pymongo import MongoClient

from ashare_lab.data.balance_sheet_store import MongoBalanceSheetStore
from ashare_lab.data.balance_sheets import build_balance_sheet_version
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.sync_service import SyncResult


@dataclass(frozen=True, slots=True)
class BalanceSheetPipelineResult:
    """Aggregate counts from a bounded PIT projection."""

    batch_count: int
    event_count: int
    inserted_count: int


def persist_balance_sheet_results(
    registry: SchemaRegistry,
    results: tuple[SyncResult, ...],
) -> BalanceSheetPipelineResult:
    """Project governed responses and persist versions plus empty-batch evidence."""
    settings = DataSettings()
    event_count = 0
    inserted_count = 0
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        store = MongoBalanceSheetStore(mongo, settings.mongodb_database)
        for result in results:
            if result.batch.snapshot.endpoint != "balancesheet":
                detail = f"unsupported balance-sheet endpoint: {result.batch.snapshot.endpoint}"
                raise SchemaContractError(detail)
            schema = registry.endpoint("balancesheet")
            canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
            events = tuple(build_balance_sheet_version(record) for record in canonical.records)
            written = store.write_batch(canonical, events)
            event_count += written.event_count
            inserted_count += written.inserted_count
    return BalanceSheetPipelineResult(len(results), event_count, inserted_count)
