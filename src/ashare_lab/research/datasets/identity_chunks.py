"""Bounded content-addressed chunks for large dataset evidence identity sets."""

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final

_CHUNK_SIZE: Final = 1_000


@unique
class IdentityKind(StrEnum):
    """Closed identity arrays stored outside Mongo owner documents."""

    SOURCE_SNAPSHOT = "source_snapshot"
    LINEAGE_EDGE = "lineage_edge"


@dataclass(frozen=True, slots=True)
class IdentityChunk:
    """One ordered, bounded, independently content-addressed identity group."""

    chunk_id: str
    owner_id: str
    identity_kind: IdentityKind
    chunk_index: int
    identity_ids: tuple[str, ...]
    content_sha256: str


def build_identity_chunks(
    owner_id: str,
    identity_kind: IdentityKind,
    identities: tuple[str, ...],
) -> tuple[IdentityChunk, ...]:
    """Split an immutable ordered identity set without truncation or sampling."""
    chunks: list[IdentityChunk] = []
    for start in range(0, len(identities), _CHUNK_SIZE):
        values = identities[start : start + _CHUNK_SIZE]
        chunk_index = start // _CHUNK_SIZE
        content_sha256 = identity_digest(values)
        identity = f"{owner_id}|{identity_kind.value}|{chunk_index}|{content_sha256}"
        chunk_id = f"dataset_identity_chunk_{hashlib.sha256(identity.encode()).hexdigest()}"
        chunks.append(
            IdentityChunk(
                chunk_id,
                owner_id,
                identity_kind,
                chunk_index,
                values,
                content_sha256,
            )
        )
    return tuple(chunks)


def identity_digest(identities: tuple[str, ...]) -> str:
    """Hash one complete ordered identity set for owner-level verification."""
    return hashlib.sha256("|".join(identities).encode()).hexdigest()
