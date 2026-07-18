"""Local Mongo composition root for governed market-factor publication."""

from datetime import date
from pathlib import Path
from typing import Final

from pymongo import MongoClient
from pymongo.database import Database

from ashare_lab.code_identity import load_git_evidence
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.artifacts.artifact_identity import artifact_descriptor
from ashare_lab.research.artifacts.artifact_io import load_manifest
from ashare_lab.research.features.market.materialization import (
    MarketFeatureMaterializationRequest,
)
from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleReadResult,
    MarketCollection,
    MarketDatabase,
)
from ashare_lab.research.features.market.mongo_reader import MongoMarketBundleReader
from ashare_lab.research.universe.mongo_reader import MongoUniversePanelReader
from ashare_lab.services.market_feature_contracts import (
    MarketFeatureMaterializationResult,
    MarketFeatureRunRequest,
    MarketFeatureServiceError,
    MarketFeatureServiceRule,
)
from ashare_lab.services.market_feature_materialization import (
    materialize_weekly_market_features,
)

_UNIVERSE_ARTIFACT_ID: Final = (
    "universe_artifact_a5e618d3b4273bc97b8720bc8a31808fed91d00446cfb5e60a6f9cac6040de1b"
)


class MongoDatabaseView:
    """Expose PyMongo through the narrow read-only research protocol."""

    def __init__(self, database: Database[BsonDocument]) -> None:
        """Retain the concrete database while freezing its governed name."""
        self.name = database.name
        self._database = database

    def __getitem__(self, name: str) -> MarketCollection:
        """Return one collection through its minimal read capability."""
        return self._database[name]


class MongoMarketFeatureReader:
    """Compose accepted calendar and five-chain readers over one database."""

    def __init__(self, database: MarketDatabase) -> None:
        """Bind both read-only adapters to the governed database."""
        self._calendar = MongoUniversePanelReader(database)
        self._market = MongoMarketBundleReader(database)

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        """Read accepted SSE open sessions from the exact market schema."""
        return self._calendar.open_dates(start_date, end_date, schema_manifest_id)

    def read(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> MarketBundleReadResult:
        """Read quality-adjudicated canonical bundles without mutation."""
        return self._market.read(start_date, end_date, schema_manifest_id)


def materialize_default_market_features(
    project_root: Path,
    start_date: date,
    end_date: date,
) -> MarketFeatureMaterializationResult:
    """Publish the fixed 15-factor family from the qualified local closure."""
    identity = load_git_evidence(project_root)
    if not identity.is_clean:
        raise MarketFeatureServiceError(
            MarketFeatureServiceRule.DIRTY_WORKTREE,
            "market feature publication requires a clean Git worktree",
        )
    settings = DataSettings()
    market_schema = SchemaRegistry.load(project_root / "schemas" / "tushare_p0_v1.json")
    schemas = ResearchSchemaCatalog.load(
        (
            project_root / "schemas" / "research_feature_row_v1.json",
            project_root / "schemas" / "research_universe_row_v1.json",
        )
    )
    artifact_root = project_root / "data" / "artifacts"
    universe_directory = artifact_root / "universe" / _UNIVERSE_ARTIFACT_ID
    manifest = load_manifest(universe_directory / "manifest.json")
    universe = artifact_descriptor(universe_directory, manifest)
    if len(manifest.upstream_artifact_ids) != 1 or len(manifest.upstream_lineage_edge_ids) != 1:
        raise MarketFeatureServiceError(
            MarketFeatureServiceRule.UNIVERSE_IDENTITY_MISMATCH,
            "universe manifest must have one qualified input closure",
        )
    materialization = MarketFeatureMaterializationRequest(
        input_manifest_id=manifest.upstream_artifact_ids[0],
        input_lineage_manifest_id=manifest.upstream_lineage_edge_ids[0],
        universe_artifact_id=manifest.artifact_id,
        universe_lineage_edge_id=manifest.lineage_edge_id,
        code_commit=identity.commit,
    )
    store = ParquetArtifactStore(artifact_root, schemas)
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as client:
        reader = MongoMarketFeatureReader(MongoDatabaseView(client[settings.mongodb_database]))
        return materialize_weekly_market_features(
            reader,
            store,
            schemas,
            MarketFeatureRunRequest(
                start_date=start_date,
                end_date=end_date,
                market_schema_manifest_id=market_schema.manifest_id,
                universe_artifact=universe,
                materialization=materialization,
            ),
        )
