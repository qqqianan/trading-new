"""Local Mongo composition root for governed financial-factor publication."""

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
from ashare_lab.research.features.financial.materialization import (
    FinancialFeatureMaterializationRequest,
)
from ashare_lab.research.features.financial.mongo_contracts import (
    FinancialCollection,
    FinancialDatabase,
)
from ashare_lab.research.features.financial.mongo_reader import MongoFinancialFactorReader
from ashare_lab.services.financial_feature_contracts import (
    FinancialFeatureMaterializationResult,
    FinancialFeatureRunRequest,
    FinancialFeatureServiceError,
    FinancialFeatureServiceRule,
)
from ashare_lab.services.financial_feature_materialization import (
    materialize_weekly_financial_features,
)

_UNIVERSE_ARTIFACT_ID: Final = (
    "universe_artifact_a5e618d3b4273bc97b8720bc8a31808fed91d00446cfb5e60a6f9cac6040de1b"
)


class MongoFinancialDatabaseView:
    """Expose PyMongo through the narrow read-only financial protocol."""

    def __init__(self, database: Database[BsonDocument]) -> None:
        """Retain the concrete database while freezing its governed name."""
        self.name = database.name
        self._database = database

    def __getitem__(self, name: str) -> FinancialCollection:
        """Return one collection through its minimal read capability."""
        return self._database[name]


def materialize_default_financial_features(
    project_root: Path,
    start_date: date,
    end_date: date,
) -> FinancialFeatureMaterializationResult:
    """Publish the fixed six-factor family from accepted PIT versions."""
    identity = load_git_evidence(project_root)
    if not identity.is_clean:
        raise FinancialFeatureServiceError(
            FinancialFeatureServiceRule.DIRTY_WORKTREE,
            "financial feature publication requires a clean Git worktree",
        )
    settings = DataSettings()
    financial_schema = SchemaRegistry.load(
        project_root / "schemas" / "tushare_financial_indicator_v1.json"
    )
    schemas = ResearchSchemaCatalog.load(
        (
            project_root / "schemas" / "research_financial_feature_row_v1.json",
            project_root / "schemas" / "research_universe_row_v1.json",
        )
    )
    artifact_root = project_root / "data" / "artifacts"
    universe_directory = artifact_root / "universe" / _UNIVERSE_ARTIFACT_ID
    manifest = load_manifest(universe_directory / "manifest.json")
    universe = artifact_descriptor(universe_directory, manifest)
    if len(manifest.upstream_artifact_ids) != 1 or len(manifest.upstream_lineage_edge_ids) != 1:
        raise FinancialFeatureServiceError(
            FinancialFeatureServiceRule.UNIVERSE_IDENTITY_MISMATCH,
            "universe manifest must have one qualified input closure",
        )
    materialization = FinancialFeatureMaterializationRequest(
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
        database: FinancialDatabase = MongoFinancialDatabaseView(client[settings.mongodb_database])
        reader = MongoFinancialFactorReader(database)
        return materialize_weekly_financial_features(
            reader,
            store,
            schemas,
            FinancialFeatureRunRequest(
                start_date=start_date,
                end_date=end_date,
                financial_schema_manifest_id=financial_schema.manifest_id,
                universe_artifact=universe,
                materialization=materialization,
            ),
        )
