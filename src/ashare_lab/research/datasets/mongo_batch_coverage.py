"""Read-only Mongo adapter for scheduled market and benchmark batch coverage."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from ashare_lab.research.datasets.batch_coverage import (
    BatchCoverageSpec,
    BatchObservation,
    audit_dated_batches,
)
from ashare_lab.research.datasets.coverage_models import ComponentCoverage, DatasetComponent
from ashare_lab.research.datasets.mongo_batch_evidence import MongoGovernedBatchReader

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.schema_registry import SchemaRegistry
    from ashare_lab.research.datasets.batch_coverage import GovernedBatchEvidence

_DAILY_ENDPOINTS: Final = ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d")
_MARKET_ENDPOINTS: Final = ("trade_cal", *_DAILY_ENDPOINTS)


class _TradeDateParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    trade_date: str


class _CalendarDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    cal_date: str
    source_snapshot_id: str


class _BenchmarkDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    trade_date: str
    source_snapshot_id: str


class MongoBatchCoverageReaderError(Exception):
    """Batch coverage reader was bound outside the governed database."""

    __slots__ = ("database_name",)

    def __init__(self, database_name: str) -> None:
        """Record the rejected database boundary."""
        super().__init__()
        self.database_name = database_name

    def __str__(self) -> str:
        """Explain the fixed database isolation rule."""
        return f"batch coverage reader requires ashare_quant, got {self.database_name}"


class MongoBatchCoverageReader:
    """Derive daily bundle facts without permitting caller-declared quality."""

    def __init__(self, database: Database[BsonDocument]) -> None:
        """Bind read-only evidence access to the isolated database."""
        if database.name != "ashare_quant":
            raise MongoBatchCoverageReaderError(database.name)
        self._database = database
        self._evidence = MongoGovernedBatchReader(database)

    def market_daily(
        self,
        registry: SchemaRegistry,
        start_date: date,
        end_date: date,
    ) -> tuple[ComponentCoverage, tuple[date, ...]]:
        """Audit the calendar and five daily endpoint batches on every open date."""
        calendar = tuple(
            _CalendarDocument.model_validate(document)
            for document in self._database["canonical_trade_calendar"].find(
                {
                    "schema_manifest_id": registry.manifest_id,
                    "quality_status": "ACCEPTED",
                    "exchange": "SSE",
                    "is_open": 1,
                    "cal_date": {"$gte": _raw_date(start_date), "$lte": _raw_date(end_date)},
                }
            )
        )
        open_dates = tuple(sorted({_date(item.cal_date) for item in calendar}))
        observations = [
            BatchObservation(_date(item.cal_date), "trade_cal", item.source_snapshot_id)
            for item in calendar
        ]
        snapshots = self._evidence.accepted_snapshots(registry.manifest_id, _DAILY_ENDPOINTS)
        for snapshot in snapshots:
            params = _TradeDateParams.model_validate_json(snapshot.request_params_canonical)
            trading_date = _date(params.trade_date)
            if start_date <= trading_date <= end_date:
                observations.append(
                    BatchObservation(trading_date, snapshot.endpoint, snapshot.snapshot_id)
                )
        snapshot_ids = tuple(sorted({item.snapshot_id for item in observations}))
        coverage = audit_dated_batches(
            BatchCoverageSpec(
                DatasetComponent.MARKET_DAILY,
                open_dates,
                _MARKET_ENDPOINTS,
                registry.manifest_id,
            ),
            tuple(observations),
            self._evidence.batch_evidence(snapshot_ids, registry.manifest_id),
        )
        return coverage, open_dates

    def benchmark_daily(
        self,
        registry: SchemaRegistry,
        required_dates: tuple[date, ...],
        benchmark_code: str,
    ) -> ComponentCoverage:
        """Audit one benchmark row and its batch evidence on every market date."""
        if not required_dates:
            return audit_dated_batches(
                BatchCoverageSpec(
                    DatasetComponent.BENCHMARK_DAILY,
                    (),
                    ("index_daily",),
                    registry.manifest_id,
                ),
                (),
                (),
            )
        schema = registry.endpoint("index_daily")
        documents = tuple(
            _BenchmarkDocument.model_validate(document)
            for document in self._database[schema.canonical_collection].find(
                {
                    "schema_manifest_id": registry.manifest_id,
                    "quality_status": "ACCEPTED",
                    "ts_code": benchmark_code,
                    "trade_date": {
                        "$gte": _raw_date(min(required_dates)),
                        "$lte": _raw_date(max(required_dates)),
                    },
                }
            )
        )
        required = set(required_dates)
        observations = tuple(
            BatchObservation(_date(item.trade_date), "index_daily", item.source_snapshot_id)
            for item in documents
            if _date(item.trade_date) in required
        )
        snapshot_ids = tuple(sorted({item.snapshot_id for item in observations}))
        return audit_dated_batches(
            BatchCoverageSpec(
                DatasetComponent.BENCHMARK_DAILY,
                required_dates,
                ("index_daily",),
                registry.manifest_id,
            ),
            observations,
            self._evidence.batch_evidence(snapshot_ids, registry.manifest_id),
        )

    def batch_evidence(
        self,
        snapshot_ids: tuple[str, ...],
        schema_manifest_id: str,
    ) -> tuple[GovernedBatchEvidence, ...]:
        """Normalize accepted Raw-to-canonical batch chains for reuse by PIT audits."""
        return self._evidence.batch_evidence(snapshot_ids, schema_manifest_id)


def _date(raw: str) -> date:
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def _raw_date(value: date) -> str:
    return value.strftime("%Y%m%d")
