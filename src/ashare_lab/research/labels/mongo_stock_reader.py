"""Exact-schema stock open, limit, and suspension evidence reader."""

from datetime import date
from typing import TYPE_CHECKING, Final

from ashare_lab.research.features.market.mongo_contracts import MarketDatabase, MarketKey
from ashare_lab.research.features.market.mongo_documents import (
    DailyDocument,
    LimitDocument,
    SuspensionDocument,
    snapshot_date,
)
from ashare_lab.research.features.market.mongo_folding import fold_canonical
from ashare_lab.research.labels.models import LabelReaderError, LabelTradeObservation
from ashare_lab.research.labels.mongo_queries import load_documents, snapshot_projection

if TYPE_CHECKING:
    from ashare_lab.data.bson_types import BsonDocument

_ENDPOINTS: Final = ("daily", "stk_limit", "suspend_d")


def read_stock_observations(
    database: MarketDatabase,
    start_date: date,
    end_date: date,
    schema_manifest_id: str,
) -> tuple[LabelTradeObservation, ...]:
    """Join raw opens with fixed-session limit or suspension evidence."""
    snapshots = _market_snapshots(database, start_date, end_date, schema_manifest_id)
    daily = fold_canonical(
        "canonical_daily_bar",
        load_documents(
            database,
            "canonical_daily_bar",
            DailyDocument,
            snapshots["daily"],
            schema_manifest_id,
        ),
        lambda item: (item.available_shanghai.isoformat(), item.open),
    )
    limits = fold_canonical(
        "canonical_daily_price_limit",
        load_documents(
            database,
            "canonical_daily_price_limit",
            LimitDocument,
            snapshots["stk_limit"],
            schema_manifest_id,
        ),
        lambda item: (item.available_shanghai.isoformat(), item.up_limit, item.down_limit),
    )
    suspensions = _suspensions(database, snapshots["suspend_d"], schema_manifest_id)
    keys = tuple(sorted({*daily, *limits, *suspensions}))
    return tuple(
        _stock_observation(key, daily.get(key), limits.get(key), suspensions.get(key))
        for key in keys
    )


def _market_snapshots(
    database: MarketDatabase,
    start_date: date,
    end_date: date,
    schema_manifest_id: str,
) -> dict[str, tuple[str, ...]]:
    query: BsonDocument = {
        "schema_manifest_id": schema_manifest_id,
        "status": "ACCEPTED",
        "endpoint": {"$in": list(_ENDPOINTS)},
    }
    parsed = tuple(
        snapshot_date(document)
        for document in database["meta_source_snapshots"].find(query, snapshot_projection())
    )
    return {
        endpoint: tuple(
            sorted(
                snapshot.snapshot_id
                for snapshot, trading_date in parsed
                if snapshot.endpoint == endpoint and start_date <= trading_date <= end_date
            )
        )
        for endpoint in _ENDPOINTS
    }


def _suspensions(
    database: MarketDatabase,
    snapshot_ids: tuple[str, ...],
    schema_manifest_id: str,
) -> dict[MarketKey, SuspensionDocument]:
    documents = load_documents(
        database,
        "canonical_suspension_event",
        SuspensionDocument,
        snapshot_ids,
        schema_manifest_id,
    )
    return fold_canonical(
        "canonical_suspension_event",
        tuple(item for item in documents if item.suspend_type == "S"),
        lambda item: (item.available_shanghai.isoformat(), item.suspend_type),
    )


def _stock_observation(
    key: MarketKey,
    daily: DailyDocument | None,
    limit: LimitDocument | None,
    suspension: SuspensionDocument | None,
) -> LabelTradeObservation:
    constraint = suspension if suspension is not None else limit
    clocks = tuple(
        item.available_shanghai for item in (daily, limit, suspension) if item is not None
    )
    if not clocks:
        detail = f"empty stock evidence union: {key[0]}:{key[1]:%Y%m%d}"
        raise LabelReaderError(detail)
    return LabelTradeObservation(
        symbol=key[0],
        trading_date=key[1],
        open_price=None if daily is None else daily.open,
        up_limit=None if limit is None else limit.up_limit,
        down_limit=None if limit is None else limit.down_limit,
        is_suspended=suspension is not None,
        available_at=max(clocks),
        price_source_snapshot_id=None if daily is None else daily.source_snapshot_id,
        price_source_row_sha256=None if daily is None else daily.source_row_sha256,
        constraint_source_snapshot_id=(
            None if constraint is None else constraint.source_snapshot_id
        ),
        constraint_source_row_sha256=None if constraint is None else constraint.source_row_sha256,
    )
