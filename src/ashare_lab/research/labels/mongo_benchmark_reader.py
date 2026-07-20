"""Exact-schema benchmark raw-open evidence reader."""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from ashare_lab.research.features.market.mongo_contracts import MarketDatabase
from ashare_lab.research.features.market.mongo_documents import DailyDocument, SnapshotDocument
from ashare_lab.research.features.market.mongo_folding import fold_canonical
from ashare_lab.research.labels.models import BenchmarkOpenObservation
from ashare_lab.research.labels.mongo_documents import benchmark_snapshot_range
from ashare_lab.research.labels.mongo_queries import load_documents, snapshot_projection

if TYPE_CHECKING:
    from ashare_lab.data.bson_types import BsonDocument


@dataclass(frozen=True, slots=True)
class BenchmarkSnapshotBoundary:
    """Exact benchmark schema and optional DatasetSpec Raw snapshot allowlist."""

    schema_manifest_id: str
    allowed_snapshot_ids: tuple[str, ...] | None


def read_benchmark_observations(
    database: MarketDatabase,
    start_date: date,
    end_date: date,
    symbol: str,
    schema_manifest_id: str,
) -> tuple[BenchmarkOpenObservation, ...]:
    """Load one exact benchmark's accepted raw opens and provenance."""
    return read_dataset_benchmark_observations(
        database,
        start_date,
        end_date,
        symbol,
        BenchmarkSnapshotBoundary(schema_manifest_id, None),
    )


def read_dataset_benchmark_observations(
    database: MarketDatabase,
    start_date: date,
    end_date: date,
    symbol: str,
    boundary: BenchmarkSnapshotBoundary,
) -> tuple[BenchmarkOpenObservation, ...]:
    """Load benchmark opens through an exact DatasetSpec snapshot boundary."""
    snapshots = _benchmark_snapshots(
        database,
        start_date,
        end_date,
        symbol,
        boundary,
    )
    documents = load_documents(
        database,
        "canonical_index_daily_bar",
        DailyDocument,
        snapshots,
        boundary.schema_manifest_id,
    )
    folded = fold_canonical(
        "canonical_index_daily_bar",
        documents,
        lambda item: (item.available_shanghai.isoformat(), item.open),
    )
    return tuple(
        BenchmarkOpenObservation(
            symbol=item.ts_code,
            trading_date=item.key[1],
            open_price=item.open,
            available_at=item.available_shanghai,
            source_snapshot_id=item.source_snapshot_id,
            source_row_sha256=item.source_row_sha256,
        )
        for key, item in sorted(folded.items())
        if key[0] == symbol and start_date <= key[1] <= end_date
    )


def _benchmark_snapshots(
    database: MarketDatabase,
    start_date: date,
    end_date: date,
    symbol: str,
    boundary: BenchmarkSnapshotBoundary,
) -> tuple[str, ...]:
    query: BsonDocument = {
        "schema_manifest_id": boundary.schema_manifest_id,
        "status": "ACCEPTED",
        "endpoint": "index_daily",
    }
    if boundary.allowed_snapshot_ids is not None:
        query["snapshot_id"] = {"$in": list(boundary.allowed_snapshot_ids)}
    parsed = tuple(
        SnapshotDocument.model_validate(document)
        for document in database["meta_source_snapshots"].find(query, snapshot_projection())
    )
    return tuple(
        sorted(
            snapshot.snapshot_id
            for snapshot in parsed
            if _overlaps(snapshot, symbol, start_date, end_date)
            and (
                boundary.allowed_snapshot_ids is None
                or snapshot.snapshot_id in boundary.allowed_snapshot_ids
            )
        )
    )


def _overlaps(
    snapshot: SnapshotDocument,
    symbol: str,
    start_date: date,
    end_date: date,
) -> bool:
    snapshot_symbol, snapshot_start, snapshot_end = benchmark_snapshot_range(snapshot)
    return snapshot_symbol == symbol and snapshot_start <= end_date and snapshot_end >= start_date
