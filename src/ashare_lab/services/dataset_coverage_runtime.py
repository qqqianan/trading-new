"""Mongo composition root for the governed dataset coverage service."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pymongo import MongoClient

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.research.datasets.artifact_store import MongoDatasetArtifactStore
from ashare_lab.research.datasets.coverage import CoverageRequest, DatasetComponent
from ashare_lab.research.datasets.mongo_coverage import (
    CoverageSchemas,
    MongoCoverageEvidenceReader,
)
from ashare_lab.services.dataset_coverage import DatasetCoverageRun, DatasetCoverageService

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def qualify_default_dataset(
    start_date: date,
    end_date: date,
    *,
    require_industry: bool,
) -> DatasetCoverageRun:
    """Derive and persist the first medium-horizon dataset evidence matrix."""
    settings = DataSettings()
    schemas = CoverageSchemas(
        market=SchemaRegistry.load(Path("schemas/tushare_p0_v1.json")),
        benchmark=SchemaRegistry.load(Path("schemas/tushare_benchmarks_v1.json")),
        universe=SchemaRegistry.load(Path("schemas/tushare_universe_v1.json")),
        financial_indicators=SchemaRegistry.load(
            Path("schemas/tushare_financial_indicator_v1.json")
        ),
        industry=SchemaRegistry.load(Path("schemas/tushare_industry_v1.json")),
    )
    components = (
        DatasetComponent.MARKET_DAILY,
        DatasetComponent.UNIVERSE,
        DatasetComponent.BENCHMARK_DAILY,
        DatasetComponent.FINANCIALS,
    )
    required = (*components, DatasetComponent.INDUSTRY) if require_industry else components
    request = CoverageRequest(start_date, end_date, required)
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as client:
        reader = MongoCoverageEvidenceReader(
            client[settings.mongodb_database],
            schemas,
            "000905.SH",
        )
        store = MongoDatasetArtifactStore(client, settings.mongodb_database)
        return DatasetCoverageService(reader, store).qualify(
            request,
            datetime.now(_SHANGHAI),
        )
