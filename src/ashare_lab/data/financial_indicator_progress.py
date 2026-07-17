"""Evidence-based resume state for financial indicators."""

from pydantic import BaseModel, ConfigDict
from pymongo import MongoClient

from ashare_lab.data.balance_sheet_progress import load_balance_sheet_security_codes
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.financial_indicator_store import indicator_batch_artifact_id
from ashare_lab.data.schema_registry import SchemaRegistry


class _Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ts_code: str
    start_date: str
    end_date: str


class _Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    snapshot_id: str
    request_params_canonical: str


class _Lineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    downstream_artifact_id: str


def load_indicator_security_codes() -> tuple[str, ...]:
    """Load accepted historical lifecycle codes without survivor filtering."""
    return load_balance_sheet_security_codes()


def load_completed_indicator_codes(
    registry: SchemaRegistry, start_date: str, end_date: str
) -> frozenset[str]:
    """Return codes with accepted Raw, canonical lineage, PIT lineage and quality."""
    settings = DataSettings()
    completed: set[str] = set()
    with MongoClient[BsonDocument](settings.mongodb_uri, serverSelectionTimeoutMS=8_000) as mongo:
        db = mongo[settings.mongodb_database]
        snapshots = db["meta_source_snapshots"].find(
            {
                "endpoint": "fina_indicator",
                "schema_manifest_id": registry.manifest_id,
                "status": "ACCEPTED",
            }
        )
        for document in snapshots:
            snapshot = _Snapshot.model_validate(document)
            params = _Params.model_validate_json(snapshot.request_params_canonical)
            if params.start_date != start_date or params.end_date != end_date:
                continue
            raw_edge = db["meta_lineage_edges"].find_one(
                {
                    "upstream_artifact_id": snapshot.snapshot_id,
                    "output_schema_id": registry.manifest_id,
                    "transform_name": "tushare_raw_to_canonical",
                }
            )
            if raw_edge is None:
                continue
            canonical = _Lineage.model_validate(raw_edge).downstream_artifact_id
            batch = indicator_batch_artifact_id(canonical)
            pit = db["meta_lineage_edges"].find_one(
                {
                    "upstream_artifact_id": canonical,
                    "downstream_artifact_id": batch,
                    "output_schema_id": registry.manifest_id,
                },
                {"_id": 1},
            )
            quality = db["meta_quality_reports"].find_one(
                {"artifact_id": batch, "passed": True}, {"_id": 1}
            )
            if pit is not None and quality is not None:
                completed.add(params.ts_code)
    return frozenset(completed)
