"""Evidence-based resume state for cash-flow backfill."""

from pydantic import BaseModel, ConfigDict
from pymongo import MongoClient

from ashare_lab.data.balance_sheet_progress import load_balance_sheet_security_codes
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.cashflow_store import cashflow_batch_artifact_id
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaRegistry


class _CashflowParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ts_code: str
    start_date: str
    end_date: str


class _SnapshotEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    snapshot_id: str
    request_params_canonical: str


class _CanonicalLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    downstream_artifact_id: str


def load_cashflow_security_codes() -> tuple[str, ...]:
    """Load the same accepted historical lifecycle universe used by financial tables."""
    return load_balance_sheet_security_codes()


def load_completed_cashflow_codes(
    registry: SchemaRegistry, start_date: str, end_date: str
) -> frozenset[str]:
    """Return codes proven complete through Raw, canonical, and PIT evidence."""
    settings = DataSettings()
    completed: set[str] = set()
    with MongoClient[BsonDocument](settings.mongodb_uri, serverSelectionTimeoutMS=8_000) as mongo:
        database = mongo[settings.mongodb_database]
        snapshots = database["meta_source_snapshots"].find(
            {
                "endpoint": "cashflow",
                "schema_manifest_id": registry.manifest_id,
                "status": "ACCEPTED",
            }
        )
        for document in snapshots:
            snapshot = _SnapshotEvidence.model_validate(document)
            params = _CashflowParams.model_validate_json(snapshot.request_params_canonical)
            if params.start_date != start_date or params.end_date != end_date:
                continue
            raw_lineage = database["meta_lineage_edges"].find_one(
                {
                    "upstream_artifact_id": snapshot.snapshot_id,
                    "output_schema_id": registry.manifest_id,
                    "transform_name": "tushare_raw_to_canonical",
                }
            )
            if raw_lineage is None:
                continue
            canonical = _CanonicalLineage.model_validate(raw_lineage)
            batch_id = cashflow_batch_artifact_id(canonical.downstream_artifact_id)
            pit_lineage = database["meta_lineage_edges"].find_one(
                {
                    "upstream_artifact_id": canonical.downstream_artifact_id,
                    "downstream_artifact_id": batch_id,
                    "output_schema_id": registry.manifest_id,
                },
                {"_id": 1},
            )
            quality = database["meta_quality_reports"].find_one(
                {"artifact_id": batch_id, "passed": True}, {"_id": 1}
            )
            if pit_lineage is not None and quality is not None:
                completed.add(params.ts_code)
    return frozenset(completed)
