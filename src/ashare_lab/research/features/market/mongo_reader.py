"""Read and quality-adjudicate five-chain daily market factor bundles."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ashare_lab.research.features.market.bundle_builder import (
    build_observation,
    suspended_market_keys,
)
from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleReaderError,
    MarketBundleReadResult,
    MarketBundleRejection,
    MarketDatabase,
    MarketKey,
)
from ashare_lab.research.features.market.mongo_documents import (
    AdjustmentDocument,
    CanonicalDocument,
    DailyDocument,
    LimitDocument,
    SuspensionDocument,
    ValuationDocument,
    snapshot_date,
)
from ashare_lab.research.features.market.mongo_folding import fold_canonical

if TYPE_CHECKING:
    from datetime import date

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.research.features.market.models import MarketFactorObservation

_ENDPOINTS: Final = ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d")


class MongoMarketBundleReader:
    """Load current-schema accepted market rows without mutating Mongo."""

    def __init__(self, database: MarketDatabase) -> None:
        """Bind only to the isolated governed database."""
        if database.name != "ashare_quant":
            raise MarketBundleReaderError(database.name)
        self._database = database

    def read(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> MarketBundleReadResult:
        """Read, fold, join, and classify one closed date interval."""
        snapshots = self._snapshots(start_date, end_date, schema_manifest_id)
        daily = self._daily(snapshots, schema_manifest_id)
        adjustments = self._adjustments(snapshots, schema_manifest_id)
        valuations = self._valuations(snapshots, schema_manifest_id)
        limits = self._limits(snapshots, schema_manifest_id)
        suspended = self._suspensions(snapshots, schema_manifest_id)
        observations: list[MarketFactorObservation] = []
        rejections: list[MarketBundleRejection] = []
        for key, bar in sorted(daily.items()):
            adjustment = adjustments.get(key)
            limit = limits.get(key)
            if adjustment is None:
                rejections.append(MarketBundleRejection(*key, "MISSING_ADJUSTMENT_FACTOR"))
                continue
            if limit is None:
                rejections.append(MarketBundleRejection(*key, "MISSING_PRICE_LIMIT"))
                continue
            if bar.pre_close is None:
                rejections.append(MarketBundleRejection(*key, "MISSING_PREVIOUS_CLOSE"))
                continue
            observations.append(
                build_observation(
                    bar,
                    adjustment,
                    valuations.get(key),
                    limit,
                )
            )
        return MarketBundleReadResult(
            observations=tuple(observations),
            rejections=tuple(rejections),
            suspended_keys=suspended_market_keys(suspended),
        )

    def _snapshots(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> dict[str, tuple[str, ...]]:
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "status": "ACCEPTED",
            "endpoint": {"$in": list(_ENDPOINTS)},
        }
        projection: BsonDocument = {
            "snapshot_id": 1,
            "endpoint": 1,
            "request_params_canonical": 1,
            "schema_manifest_id": 1,
            "status": 1,
        }
        parsed = tuple(
            snapshot_date(document)
            for document in self._database["meta_source_snapshots"].find(query, projection)
        )
        return {
            endpoint: tuple(
                sorted(
                    snapshot.snapshot_id
                    for snapshot, trade_date in parsed
                    if snapshot.endpoint == endpoint
                    and snapshot.schema_manifest_id == schema_manifest_id
                    and snapshot.status == "ACCEPTED"
                    and start_date <= trade_date <= end_date
                )
            )
            for endpoint in _ENDPOINTS
        }

    def _documents[T: CanonicalDocument](
        self,
        collection: str,
        model: type[T],
        snapshot_ids: tuple[str, ...],
        schema_manifest_id: str,
    ) -> tuple[T, ...]:
        if not snapshot_ids:
            return ()
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "quality_status": "ACCEPTED",
            "source_snapshot_id": {"$in": list(snapshot_ids)},
        }
        projection: BsonDocument = {"_id": 0}
        projection.update(dict.fromkeys(model.model_fields, 1))
        return tuple(
            model.model_validate(document)
            for document in self._database[collection].find(query, projection)
        )

    def _daily(
        self, snapshots: dict[str, tuple[str, ...]], schema: str
    ) -> dict[MarketKey, DailyDocument]:
        documents = self._documents(
            "canonical_daily_bar", DailyDocument, snapshots["daily"], schema
        )
        return fold_canonical(
            "canonical_daily_bar",
            documents,
            lambda item: (
                item.available_shanghai.isoformat(),
                item.open,
                item.high,
                item.low,
                item.close,
                item.pre_close,
                item.vol,
                item.amount,
            ),
        )

    def _adjustments(
        self, snapshots: dict[str, tuple[str, ...]], schema: str
    ) -> dict[MarketKey, AdjustmentDocument]:
        documents = self._documents(
            "canonical_adjustment_factor", AdjustmentDocument, snapshots["adj_factor"], schema
        )
        return fold_canonical(
            "canonical_adjustment_factor",
            documents,
            lambda item: (item.available_shanghai.isoformat(), item.adj_factor),
        )

    def _valuations(
        self, snapshots: dict[str, tuple[str, ...]], schema: str
    ) -> dict[MarketKey, ValuationDocument]:
        documents = self._documents(
            "canonical_daily_valuation", ValuationDocument, snapshots["daily_basic"], schema
        )
        return fold_canonical(
            "canonical_daily_valuation",
            documents,
            lambda item: (
                item.available_shanghai.isoformat(),
                item.turnover_rate,
                item.total_mv,
                item.pe_ttm,
                item.pb,
                item.ps_ttm,
                item.dv_ttm,
            ),
        )

    def _limits(
        self, snapshots: dict[str, tuple[str, ...]], schema: str
    ) -> dict[MarketKey, LimitDocument]:
        documents = self._documents(
            "canonical_daily_price_limit", LimitDocument, snapshots["stk_limit"], schema
        )
        return fold_canonical(
            "canonical_daily_price_limit",
            documents,
            lambda item: (item.available_shanghai.isoformat(), item.up_limit, item.down_limit),
        )

    def _suspensions(
        self, snapshots: dict[str, tuple[str, ...]], schema: str
    ) -> tuple[SuspensionDocument, ...]:
        return self._documents(
            "canonical_suspension_event", SuspensionDocument, snapshots["suspend_d"], schema
        )
