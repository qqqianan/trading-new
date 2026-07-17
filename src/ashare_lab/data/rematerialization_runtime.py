"""Owned Mongo composition root for append-only lineage rematerialization."""

from __future__ import annotations

from enum import StrEnum, unique
from pathlib import Path
from typing import TYPE_CHECKING

from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical_store import MongoCanonicalStore
from ashare_lab.data.config import DataSettings
from ashare_lab.data.financial_indicator_store import MongoFinancialIndicatorStore
from ashare_lab.data.industry_store import MongoIndustryStore
from ashare_lab.data.mongo_raw_replay import MongoRawReplayReader
from ashare_lab.data.rematerialization import (
    RematerializationJob,
    RematerializationProjector,
    RematerializationResult,
    rematerialize_batches,
)
from ashare_lab.data.rematerialization_checkpoint import MongoRematerializationCheckpoint
from ashare_lab.data.rematerialization_projectors import (
    CanonicalOnlyProjector,
    FinancialIndicatorProjector,
    IndustryProjector,
    UniverseProjector,
)
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.universe_store import MongoUniverseEventStore

if TYPE_CHECKING:
    from pymongo.database import Database

_MARKET_SCHEMA = Path("schemas/tushare_p0_v1.json")
_BENCHMARK_SCHEMA = Path("schemas/tushare_benchmarks_v1.json")
_UNIVERSE_SCHEMA = Path("schemas/tushare_universe_v1.json")
_FINANCIAL_INDICATOR_SCHEMA = Path("schemas/tushare_financial_indicator_v1.json")
_INDUSTRY_SCHEMA = Path("schemas/tushare_industry_v1.json")


@unique
class RematerializationTarget(StrEnum):
    """Closed governed source bundles eligible for offline replay."""

    MARKET = "market"
    BENCHMARK_DAILY = "benchmark_daily"
    UNIVERSE = "universe"
    FINANCIAL_INDICATORS = "financial_indicators"
    INDUSTRY = "industry"


def rematerialize_target(
    target: RematerializationTarget,
    max_batches: int,
) -> RematerializationResult:
    """Replay one registered bundle without network access or Raw writes."""
    settings = DataSettings()
    registry, endpoints = target_contract(target)
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as client:
        database = client[settings.mongodb_database]
        return rematerialize_batches(
            RematerializationJob(
                registry,
                endpoints,
                MongoRawReplayReader(database),
                MongoCanonicalStore(client, settings.mongodb_database),
                _projector(target, client, database),
                MongoRematerializationCheckpoint(client, settings.mongodb_database),
            ),
            max_batches=max_batches,
        )


def target_contract(
    target: RematerializationTarget,
) -> tuple[SchemaRegistry, tuple[str, ...]]:
    """Resolve one target to its immutable schema and endpoint allowlist."""
    match target:
        case RematerializationTarget.MARKET:
            return SchemaRegistry.load(_MARKET_SCHEMA), (
                "trade_cal",
                "daily",
                "adj_factor",
                "daily_basic",
                "stk_limit",
                "suspend_d",
            )
        case RematerializationTarget.BENCHMARK_DAILY:
            return SchemaRegistry.load(_BENCHMARK_SCHEMA), ("index_daily",)
        case RematerializationTarget.UNIVERSE:
            return SchemaRegistry.load(_UNIVERSE_SCHEMA), ("stock_basic", "namechange")
        case RematerializationTarget.FINANCIAL_INDICATORS:
            return SchemaRegistry.load(_FINANCIAL_INDICATOR_SCHEMA), ("fina_indicator",)
        case RematerializationTarget.INDUSTRY:
            return SchemaRegistry.load(_INDUSTRY_SCHEMA), ("index_member",)


def _projector(
    target: RematerializationTarget,
    client: MongoClient[BsonDocument],
    database: Database[BsonDocument],
) -> RematerializationProjector:
    match target:
        case RematerializationTarget.MARKET | RematerializationTarget.BENCHMARK_DAILY:
            return CanonicalOnlyProjector()
        case RematerializationTarget.UNIVERSE:
            return UniverseProjector(MongoUniverseEventStore(client, database.name))
        case RematerializationTarget.FINANCIAL_INDICATORS:
            return FinancialIndicatorProjector(MongoFinancialIndicatorStore(client, database.name))
        case RematerializationTarget.INDUSTRY:
            return IndustryProjector(MongoIndustryStore(client, database.name))
