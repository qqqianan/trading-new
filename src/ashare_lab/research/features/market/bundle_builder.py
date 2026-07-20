"""Construct complete factor observations from folded canonical bundles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ashare_lab.domain.market import MarketBar, PriceBasis, Symbol
from ashare_lab.research.features.market.models import MarketFactorObservation
from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleConflictError,
    MarketKey,
)

if TYPE_CHECKING:
    from datetime import date

    from ashare_lab.research.features.market.mongo_documents import (
        AdjustmentDocument,
        DailyDocument,
        LimitDocument,
        SuspensionDocument,
        ValuationDocument,
    )


def build_observation(
    daily: DailyDocument,
    adjustment: AdjustmentDocument,
    valuation: ValuationDocument | None,
    limit: LimitDocument,
) -> MarketFactorObservation:
    """Join one complete natural key and normalize provider units."""
    available_at = max(
        daily.available_shanghai,
        adjustment.available_shanghai,
        limit.available_shanghai,
        valuation.available_shanghai if valuation is not None else daily.available_shanghai,
    )
    artifacts = [daily.record_id, adjustment.record_id, limit.record_id]
    snapshots = [
        daily.source_snapshot_id,
        adjustment.source_snapshot_id,
        limit.source_snapshot_id,
    ]
    if valuation is not None:
        artifacts.append(valuation.record_id)
        snapshots.append(valuation.source_snapshot_id)
    return MarketFactorObservation(
        bar=MarketBar(
            symbol=Symbol(daily.ts_code),
            trading_date=daily.key[1],
            available_at=available_at,
            price_basis=PriceBasis.RAW,
            open=daily.open,
            high=daily.high,
            low=daily.low,
            close=daily.close,
            volume=int(daily.vol * 100.0),
            previous_close=daily.pre_close or 0.0,
            limit_up=limit.up_limit,
            limit_down=limit.down_limit,
            is_suspended=False,
        ),
        adjustment_factor=adjustment.adj_factor,
        turnover_rate=valuation.turnover_rate if valuation is not None else None,
        amount_cny=daily.amount * 1_000.0,
        total_mv_ten_thousand_cny=valuation.total_mv if valuation is not None else None,
        pe_ttm=valuation.pe_ttm if valuation is not None else None,
        pb=valuation.pb if valuation is not None else None,
        ps_ttm=valuation.ps_ttm if valuation is not None else None,
        dv_ttm_percent=valuation.dv_ttm if valuation is not None else None,
        source_artifact_ids=tuple(sorted(artifacts)),
        source_snapshot_ids=tuple(sorted(set(snapshots))),
    )


def suspended_market_keys(
    documents: tuple[SuspensionDocument, ...],
) -> tuple[MarketKey, ...]:
    """Fold the three-part suspension key without conflating resumptions."""
    identities: dict[tuple[str, date, str], tuple[str, str]] = {}
    suspended: set[MarketKey] = set()
    for document in documents:
        identity = (*document.key, document.suspend_type)
        material = (document.available_shanghai.isoformat(), document.source_row_sha256)
        previous = identities.get(identity)
        if previous is not None and previous != material:
            collection = "canonical_suspension_event"
            raise MarketBundleConflictError(collection, document.key)
        identities[identity] = material
        if document.suspend_type == "S":
            suspended.add(document.key)
    return tuple(sorted(suspended))
