"""Serialization helpers for bounded dataset evidence identity chunks."""

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.research.datasets.identity_chunks import (
    IdentityChunk,
    IdentityKind,
    build_identity_chunks,
    identity_digest,
)


def identity_chunk_document(chunk: IdentityChunk) -> BsonDocument:
    """Serialize one bounded evidence identity chunk."""
    return {
        "_id": chunk.chunk_id,
        "identity_chunk_id": chunk.chunk_id,
        "owner_id": chunk.owner_id,
        "identity_kind": chunk.identity_kind.value,
        "chunk_index": chunk.chunk_index,
        "identity_ids": list(chunk.identity_ids),
        "identity_count": len(chunk.identity_ids),
        "content_sha256": chunk.content_sha256,
    }


def owner_identity_chunks(
    owner_id: str,
    source_snapshot_ids: tuple[str, ...],
    lineage_edge_ids: tuple[str, ...],
) -> tuple[IdentityChunk, ...]:
    """Build both closed identity kinds for one owner."""
    return (
        *build_identity_chunks(owner_id, IdentityKind.SOURCE_SNAPSHOT, source_snapshot_ids),
        *build_identity_chunks(owner_id, IdentityKind.LINEAGE_EDGE, lineage_edge_ids),
    )


def identity_reference_fields(
    owner_id: str,
    source_snapshot_ids: tuple[str, ...],
    lineage_edge_ids: tuple[str, ...],
) -> BsonDocument:
    """Serialize chunk references, counts, and full-set digests for one owner."""
    chunks = owner_identity_chunks(owner_id, source_snapshot_ids, lineage_edge_ids)
    source_chunks = tuple(
        chunk.chunk_id for chunk in chunks if chunk.identity_kind is IdentityKind.SOURCE_SNAPSHOT
    )
    lineage_chunks = tuple(
        chunk.chunk_id for chunk in chunks if chunk.identity_kind is IdentityKind.LINEAGE_EDGE
    )
    return {
        "source_snapshot_chunk_ids": list(source_chunks),
        "source_snapshot_count": len(source_snapshot_ids),
        "source_snapshot_sha256": identity_digest(source_snapshot_ids),
        "lineage_edge_chunk_ids": list(lineage_chunks),
        "lineage_edge_count": len(lineage_edge_ids),
        "lineage_edge_sha256": identity_digest(lineage_edge_ids),
    }
