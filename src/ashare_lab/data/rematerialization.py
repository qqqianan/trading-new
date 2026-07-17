"""Model-independent replay orchestration from immutable Raw to governed artifacts."""

from dataclasses import dataclass
from typing import Protocol

from ashare_lab.data.canonical import CanonicalBatch, canonicalize_batch
from ashare_lab.data.canonical_store import CanonicalWriteResult
from ashare_lab.data.schema_registry import EndpointSchema, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotBatch


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """PIT projection counts for one canonical batch."""

    event_count: int
    inserted_count: int


@dataclass(frozen=True, slots=True)
class RematerializationResult:
    """Aggregate append-only replay outcome."""

    batch_count: int
    record_count: int
    canonical_inserted_count: int
    event_count: int
    event_inserted_count: int


class RawReplaySource(Protocol):
    """Capability that reads complete accepted Raw batches."""

    def accepted_snapshot_ids(
        self,
        registry: SchemaRegistry,
        endpoints: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return stable current-schema Raw identities."""
        ...

    def load_batch(self, registry: SchemaRegistry, snapshot_id: str) -> SnapshotBatch:
        """Load and strictly validate one immutable Raw response."""
        ...


class CanonicalSink(Protocol):
    """Capability that appends canonical records and versioned lineage."""

    def write(self, schema: EndpointSchema, batch: CanonicalBatch) -> CanonicalWriteResult:
        """Persist one deterministic canonical artifact."""
        ...


class RematerializationProjector(Protocol):
    """Optional canonical-to-PIT projection behind replay orchestration."""

    def project(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        """Persist deterministic downstream evidence for one batch."""
        ...


def rematerialize_batches(
    registry: SchemaRegistry,
    endpoints: tuple[str, ...],
    source: RawReplaySource,
    canonical_sink: CanonicalSink,
    projector: RematerializationProjector,
) -> RematerializationResult:
    """Replay every accepted Raw batch without provider access or Raw mutation."""
    batch_count = record_count = canonical_inserted = event_count = event_inserted = 0
    for snapshot_id in source.accepted_snapshot_ids(registry, endpoints):
        batch = source.load_batch(registry, snapshot_id)
        schema = registry.endpoint(batch.snapshot.endpoint)
        canonical = canonicalize_batch(batch, schema, registry.manifest_id)
        written = canonical_sink.write(schema, canonical)
        projected = projector.project(batch, canonical)
        batch_count += 1
        record_count += written.record_count
        canonical_inserted += written.inserted_count
        event_count += projected.event_count
        event_inserted += projected.inserted_count
    return RematerializationResult(
        batch_count,
        record_count,
        canonical_inserted,
        event_count,
        event_inserted,
    )
