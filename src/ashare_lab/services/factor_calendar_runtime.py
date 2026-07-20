"""Dataset-bound Mongo calendar adapter for frozen research splits."""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.splits.walk_forward import DEVELOPMENT_END
from ashare_lab.research.universe.mongo_documents import parse_date


class FactorCalendarRuntimeError(Exception):
    """Canonical sessions cannot prove one frozen DatasetSpec split calendar."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable calendar boundary failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the calendar boundary and concrete blocker."""
        return f"factor_calendar_runtime: {self.detail}"


class FactorCalendarDocument(BaseModel):
    """Exact canonical fields proving one observed exchange session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cal_date: str = Field(pattern=r"^[0-9]{8}$")
    is_open: int = Field(ge=0, le=1)
    quality_status: str
    schema_manifest_id: str
    source_snapshot_id: str
    source_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def material_identity(self) -> tuple[int, str, str]:
        """Return fields that must agree across canonical replays."""
        return (self.is_open, self.source_snapshot_id, self.source_row_sha256)


def load_dataset_development_calendar(
    project_root: Path,
    spec: DatasetSpec,
) -> tuple[date, ...]:
    """Read accepted SSE sessions and bind every row to DatasetSpec snapshots."""
    schema_id = SchemaRegistry.load(project_root / "schemas" / "tushare_p0_v1.json").manifest_id
    end_date = min(spec.end_date, DEVELOPMENT_END)
    query: BsonDocument = {
        "schema_manifest_id": schema_id,
        "quality_status": "ACCEPTED",
        "exchange": "SSE",
        "cal_date": {
            "$gte": spec.start_date.strftime("%Y%m%d"),
            "$lte": end_date.strftime("%Y%m%d"),
        },
    }
    projection: BsonDocument = {
        "_id": 0,
        "cal_date": 1,
        "is_open": 1,
        "quality_status": 1,
        "schema_manifest_id": 1,
        "source_snapshot_id": 1,
        "source_row_sha256": 1,
    }
    settings = DataSettings()
    try:
        with MongoClient[BsonDocument](
            settings.mongodb_uri,
            serverSelectionTimeoutMS=8_000,
        ) as client:
            documents = tuple(
                FactorCalendarDocument.model_validate(document)
                for document in client[settings.mongodb_database]["canonical_trade_calendar"].find(
                    query, projection
                )
            )
    except (PyMongoError, ValidationError) as error:
        detail = "canonical trade calendar cannot be read through its typed boundary"
        raise FactorCalendarRuntimeError(detail) from error
    return verified_development_calendar(documents, spec, schema_id)


def verified_development_calendar(
    documents: tuple[FactorCalendarDocument, ...],
    spec: DatasetSpec,
    schema_manifest_id: str,
) -> tuple[date, ...]:
    """Fold identical replays and reject rows outside frozen dataset evidence."""
    if schema_manifest_id not in spec.input_schema_manifest_ids:
        detail = "trade-calendar schema is absent from DatasetSpec"
        raise FactorCalendarRuntimeError(detail)
    allowed_snapshots = set(spec.source_snapshot_ids)
    states: dict[str, tuple[int, str, str]] = {}
    for document in documents:
        if (
            document.quality_status != "ACCEPTED"
            or document.schema_manifest_id != schema_manifest_id
        ):
            detail = f"calendar row crosses schema or quality boundary: {document.cal_date}"
            raise FactorCalendarRuntimeError(detail)
        if document.source_snapshot_id not in allowed_snapshots:
            detail = f"calendar snapshot is outside DatasetSpec: {document.source_snapshot_id}"
            raise FactorCalendarRuntimeError(detail)
        previous = states.get(document.cal_date)
        if previous is not None and previous != document.material_identity:
            detail = f"calendar natural key has conflicting accepted facts: {document.cal_date}"
            raise FactorCalendarRuntimeError(detail)
        states[document.cal_date] = document.material_identity
    dates = tuple(
        parse_date(day)
        for day, identity in sorted(states.items())
        if identity[0] == 1
        and spec.start_date <= parse_date(day) <= min(spec.end_date, DEVELOPMENT_END)
    )
    if not dates:
        detail = "DatasetSpec-bound development calendar is empty"
        raise FactorCalendarRuntimeError(detail)
    return dates
