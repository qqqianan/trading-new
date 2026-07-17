"""Single governed execution path for all registered Tushare requests."""

from pymongo import MongoClient
from rich.console import Console

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.canonical_store import MongoCanonicalStore
from ashare_lab.data.config import DataSettings
from ashare_lab.data.http_client import create_provider_client
from ashare_lab.data.mongo_store import MongoRawStore
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.sync_service import RequestPacer, SyncResult, TushareSyncService
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

_CONSOLE = Console()


def execute_queries(
    registry: SchemaRegistry,
    queries: tuple[TushareQuery, ...],
) -> tuple[SyncResult, ...]:
    """Run registered queries through the provider, Raw, and canonical gates."""
    settings = DataSettings()
    with MongoClient[BsonDocument](settings.mongodb_uri, serverSelectionTimeoutMS=8_000) as mongo:
        store = MongoRawStore(mongo, settings.mongodb_database)
        canonical_store = MongoCanonicalStore(mongo, settings.mongodb_database)
        store.initialize(registry)
        with create_provider_client() as http:
            client = TushareClient(settings.tushare_token.get_secret_value(), http)
            service = TushareSyncService(
                registry,
                client,
                store,
                RequestPacer(settings.tushare_min_request_interval_seconds),
            )
            results: list[SyncResult] = []
            for query in queries:
                result = service.sync(query)
                results.append(result)
                schema = registry.endpoint(query.endpoint)
                canonical = canonicalize_batch(result.batch, schema, registry.manifest_id)
                canonical_result = canonical_store.write(schema, canonical)
                state = "inserted" if result.inserted else "existing"
                _CONSOLE.print(
                    f"{query.endpoint}: raw={state} rows={result.row_count} "
                    f"canonical_inserted={canonical_result.inserted_count} "
                    f"quality={canonical_result.quality_status}"
                )
    return tuple(results)
