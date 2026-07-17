"""Evidence-based resume state for balance-sheet backfill."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter
from pymongo import MongoClient

from ashare_lab.data.balance_sheet_store import balance_sheet_batch_artifact_id
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaRegistry

_UNIVERSE_SCHEMA_PATH = Path("schemas/tushare_universe_v1.json")


class _BalanceSheetParams(BaseModel):
    """Typed standard balance-sheet request parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ts_code: str
    start_date: str
    end_date: str


class _SnapshotEvidence(BaseModel):
    """Accepted Raw fields needed to prove range completion."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    request_params_canonical: str


class _CanonicalLineage(BaseModel):
    """Canonical artifact derived from an accepted Raw snapshot."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    downstream_artifact_id: str


def load_balance_sheet_security_codes() -> tuple[str, ...]:
    """Load accepted historical lifecycle codes without survivor filtering."""
    settings = DataSettings()
    universe = SchemaRegistry.load(_UNIVERSE_SCHEMA_PATH)
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        raw_codes = mongo[settings.mongodb_database]["pit_security_events"].distinct(
            "ts_code",
            {
                "schema_manifest_id": universe.manifest_id,
                "quality_status": "ACCEPTED",
                "event_type": {"$in": ["LISTED", "FIRST_TRADED"]},
            },
        )
    return tuple(sorted(TypeAdapter(list[str]).validate_python(raw_codes)))


def load_completed_balance_sheet_codes(
    registry: SchemaRegistry,
    start_date: str,
    end_date: str,
) -> frozenset[str]:
    """Return codes proven complete through Raw, canonical, and PIT evidence."""
    settings = DataSettings()
    completed: set[str] = set()
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as mongo:
        database = mongo[settings.mongodb_database]
        snapshots = database["meta_source_snapshots"].find(
            {
                "endpoint": "balancesheet",
                "schema_manifest_id": registry.manifest_id,
                "status": "ACCEPTED",
            }
        )
        for document in snapshots:
            snapshot = _SnapshotEvidence.model_validate(document)
            params = _BalanceSheetParams.model_validate_json(snapshot.request_params_canonical)
            if params.start_date != start_date or params.end_date != end_date:
                continue
            canonical_document = database["meta_lineage_edges"].find_one(
                {
                    "upstream_artifact_id": snapshot.snapshot_id,
                    "output_schema_id": registry.manifest_id,
                    "transform_name": "tushare_raw_to_canonical",
                }
            )
            if canonical_document is None:
                continue
            canonical = _CanonicalLineage.model_validate(canonical_document)
            batch_id = balance_sheet_batch_artifact_id(canonical.downstream_artifact_id)
            pit_lineage = database["meta_lineage_edges"].find_one(
                {
                    "upstream_artifact_id": canonical.downstream_artifact_id,
                    "downstream_artifact_id": batch_id,
                    "output_schema_id": registry.manifest_id,
                },
                {"_id": 1},
            )
            quality = database["meta_quality_reports"].find_one(
                {"artifact_id": batch_id, "passed": True},
                {"_id": 1},
            )
            if pit_lineage is not None and quality is not None:
                completed.add(params.ts_code)
    return frozenset(completed)
