"""Orchestrate one Tushare request into an immutable MongoDB snapshot."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import sleep
from zoneinfo import ZoneInfo

from ashare_lab.data.mongo_store import MongoRawStore, StoredSnapshot
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotBatch, SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class RequestPacer:
    """Enforce a minimum delay before every provider request, including first use."""

    minimum_interval_seconds: float = 1.2
    sleeper: Callable[[float], None] = sleep

    def wait(self) -> None:
        """Apply the configured request interval without exposing provider credentials."""
        self.sleeper(self.minimum_interval_seconds)


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Stored outcome plus the exact validated Raw batch for downstream conversion."""

    stored: StoredSnapshot
    batch: SnapshotBatch

    @property
    def snapshot_id(self) -> str:
        """Return the Raw snapshot identity."""
        return self.stored.snapshot_id

    @property
    def row_count(self) -> int:
        """Return provider row count."""
        return self.stored.row_count

    @property
    def inserted(self) -> bool:
        """Report whether Raw storage inserted a new snapshot."""
        return self.stored.inserted


class TushareSyncService:
    """Fetch, validate, hash, and append one registered endpoint response."""

    def __init__(
        self,
        registry: SchemaRegistry,
        client: TushareClient,
        store: MongoRawStore,
        pacer: RequestPacer | None = None,
    ) -> None:
        """Bind the only registry, provider client, and Raw store for this service."""
        self._registry = registry
        self._client = client
        self._store = store
        self._pacer = pacer if pacer is not None else RequestPacer()

    def sync(self, query: TushareQuery) -> SyncResult:
        """Persist one query only after the provider matches its committed schema."""
        schema = self._registry.endpoint(query.endpoint)
        self._pacer.wait()
        requested_at = datetime.now(_SHANGHAI)
        table = self._client.fetch(query)
        completed_at = datetime.now(_SHANGHAI)
        batch = build_raw_snapshot(
            query,
            table,
            schema,
            self._registry.manifest_id,
            SnapshotTiming(requested_at=requested_at, completed_at=completed_at),
        )
        return SyncResult(stored=self._store.write_batch(schema, batch), batch=batch)
