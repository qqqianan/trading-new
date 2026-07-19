"""Local Mongo composition root for governed future-label publication."""

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
from ashare_lab.research.features.market.mongo_contracts import MarketCollection, MarketDatabase
from ashare_lab.research.labels.materialization import LabelMaterializationRequest
from ashare_lab.research.labels.mongo_reader import MongoLabelEvidenceReader
from ashare_lab.services.label_contracts import (
    LabelMaterializationResult,
    LabelRunRequest,
    LabelServiceError,
    LabelServiceRule,
)
from ashare_lab.services.label_materialization import materialize_weekly_labels

_UNIVERSE_ARTIFACT_ID: Final = (
    "universe_artifact_a5e618d3b4273bc97b8720bc8a31808fed91d00446cfb5e60a6f9cac6040de1b"
)


class MongoLabelDatabaseView:
    """Expose PyMongo through the narrow read-only label protocol."""

    def __init__(self, database: Database[BsonDocument]) -> None:
        """Retain the concrete database while freezing its governed name."""
        self.name = database.name
        self._database = database

    def __getitem__(self, name: str) -> MarketCollection:
        """Return one collection through its minimal read capability."""
        return self._database[name]


def materialize_default_labels(
    project_root: Path,
    start_date: date,
    end_date: date,
    evidence_end_date: date,
) -> LabelMaterializationResult:
    """Publish the fixed future target from the qualified local closure."""
    identity = load_git_evidence(project_root)
    if not identity.is_clean:
        raise LabelServiceError(
            LabelServiceRule.DIRTY_WORKTREE,
            "label publication requires a clean Git worktree",
        )
    market_schema = SchemaRegistry.load(project_root / "schemas" / "tushare_p0_v1.json")
    benchmark_schema = SchemaRegistry.load(project_root / "schemas" / "tushare_benchmarks_v1.json")
    schemas = ResearchSchemaCatalog.load(
        (
            project_root / "schemas" / "research_label_row_v1.json",
            project_root / "schemas" / "research_universe_row_v1.json",
        )
    )
    artifact_root = project_root / "data" / "artifacts"
    universe_directory = artifact_root / "universe" / _UNIVERSE_ARTIFACT_ID
    manifest = load_manifest(universe_directory / "manifest.json")
    universe = artifact_descriptor(universe_directory, manifest)
    if len(manifest.upstream_artifact_ids) != 1 or len(manifest.upstream_lineage_edge_ids) != 1:
        raise LabelServiceError(
            LabelServiceRule.UNIVERSE_IDENTITY_MISMATCH,
            "universe manifest must have one qualified input closure",
        )
    request = LabelRunRequest(
        start_date=start_date,
        end_date=end_date,
        evidence_end_date=evidence_end_date,
        market_schema_manifest_id=market_schema.manifest_id,
        benchmark_schema_manifest_id=benchmark_schema.manifest_id,
        universe_artifact=universe,
        materialization=LabelMaterializationRequest(
            input_manifest_id=manifest.upstream_artifact_ids[0],
            input_lineage_manifest_id=manifest.upstream_lineage_edge_ids[0],
            universe_artifact_id=manifest.artifact_id,
            universe_lineage_edge_id=manifest.lineage_edge_id,
            code_commit=identity.commit,
        ),
    )
    settings = DataSettings()
    store = ParquetArtifactStore(artifact_root, schemas)
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as client:
        database: MarketDatabase = MongoLabelDatabaseView(client[settings.mongodb_database])
        return materialize_weekly_labels(
            MongoLabelEvidenceReader(database),
            store,
            schemas,
            request,
        )
