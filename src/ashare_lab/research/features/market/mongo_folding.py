"""Natural-key folding and conflict detection for canonical market rows."""

from collections.abc import Callable

from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleConflictError,
    MarketKey,
)
from ashare_lab.research.features.market.mongo_documents import CanonicalDocument

type MaterialValue = str | float | bool | None


def fold_canonical[T: CanonicalDocument](
    collection: str,
    documents: tuple[T, ...],
    material: Callable[[T], tuple[MaterialValue, ...]],
) -> dict[MarketKey, T]:
    """Fold identical immutable replays and reject material conflicts."""
    folded: dict[MarketKey, T] = {}
    identities: dict[MarketKey, tuple[MaterialValue, ...]] = {}
    for document in documents:
        fingerprint = (*material(document), document.source_row_sha256)
        previous = identities.get(document.key)
        if previous is not None and previous != fingerprint:
            raise MarketBundleConflictError(collection, document.key)
        current = folded.get(document.key)
        if current is None or document.record_id < current.record_id:
            folded[document.key] = document
            identities[document.key] = fingerprint
    return folded
