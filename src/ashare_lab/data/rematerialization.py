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
    skipped_completed_count: int
    has_more: bool


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

    def write_replayed(
        self,
        schema: EndpointSchema,
        batch: CanonicalBatch,
    ) -> CanonicalWriteResult:
        """Persist missing canonical rows and current replay evidence."""
        ...


class RematerializationProjector(Protocol):
    """Optional canonical-to-PIT projection behind replay orchestration."""

    def project(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        """Persist deterministic downstream evidence for one batch."""
        ...


class RematerializationCheckpoint(Protocol):
    """Final evidence boundary written only after every projection succeeds."""

    def is_complete(self, snapshot_id: str, schema_manifest_id: str) -> bool:
        """Return whether this exact Raw-to-output replay already completed."""
        ...

    def complete(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> None:
        """Append one content-addressed final completion edge."""
        ...


@dataclass(frozen=True, slots=True)
class RematerializationJob:
    """Closed dependency bundle for one governed replay target."""

    registry: SchemaRegistry
    endpoints: tuple[str, ...]
    source: RawReplaySource
    canonical_sink: CanonicalSink
    projector: RematerializationProjector
    checkpoint: RematerializationCheckpoint


def rematerialize_batches(
    job: RematerializationJob,
    *,
    max_batches: int,
) -> RematerializationResult:
    """Replay every accepted Raw batch without provider access or Raw mutation."""
    batch_count = record_count = canonical_inserted = event_count = event_inserted = 0
    skipped_completed = 0
    has_more = False
    for snapshot_id in job.source.accepted_snapshot_ids(job.registry, job.endpoints):
        if job.checkpoint.is_complete(snapshot_id, job.registry.manifest_id):
            skipped_completed += 1
            continue
        if batch_count >= max_batches:
            has_more = True
            break
        batch = job.source.load_batch(job.registry, snapshot_id)
        schema = job.registry.endpoint(batch.snapshot.endpoint)
        canonical = canonicalize_batch(batch, schema, job.registry.manifest_id)
        written = job.canonical_sink.write_replayed(schema, canonical)
        projected = job.projector.project(batch, canonical)
        job.checkpoint.complete(batch, canonical)
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
        skipped_completed,
        has_more,
    )
