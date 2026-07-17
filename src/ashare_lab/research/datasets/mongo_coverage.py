"""Unified read-only Mongo evidence matrix for dataset qualification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from ashare_lab.research.datasets.coverage_models import (
    ComponentCoverage,
    CoverageRequest,
    DatasetComponent,
)
from ashare_lab.research.datasets.mongo_batch_coverage import MongoBatchCoverageReader
from ashare_lab.research.datasets.mongo_evidence import (
    ArtifactEvidenceAudit,
    EvidenceCollection,
    MongoDatasetEvidenceReader,
)
from ashare_lab.research.datasets.mongo_financial_coverage import MongoFinancialCoverageReader

if TYPE_CHECKING:
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.schema_registry import SchemaRegistry


@dataclass(frozen=True, slots=True)
class CoverageSchemas:
    """Exact schema registries required by the first research dataset design."""

    market: SchemaRegistry
    benchmark: SchemaRegistry
    universe: SchemaRegistry
    financial_indicators: SchemaRegistry
    industry: SchemaRegistry


class _DateBounds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    start: datetime
    end: datetime


class MongoCoverageEvidenceReader:
    """Compose batch and PIT facts without making qualification decisions."""

    def __init__(
        self,
        database: Database[BsonDocument],
        schemas: CoverageSchemas,
        benchmark_code: str,
    ) -> None:
        """Bind the fixed schemas and benchmark before any report request."""
        self._database = database
        self._schemas = schemas
        self._benchmark_code = benchmark_code
        self._batch = MongoBatchCoverageReader(database)
        self._pit = MongoDatasetEvidenceReader(database)
        self._financial = MongoFinancialCoverageReader(database, self._batch)

    def components(self, request: CoverageRequest) -> tuple[ComponentCoverage, ...]:
        """Return only requested component facts in stable component order."""
        market, open_dates = self._batch.market_daily(
            self._schemas.market,
            request.start_date,
            request.end_date,
        )
        components: list[ComponentCoverage] = []
        for component in sorted(set(request.required_components), key=lambda item: item.value):
            match component:
                case DatasetComponent.MARKET_DAILY:
                    evidence = market
                case DatasetComponent.BENCHMARK_DAILY:
                    evidence = self._batch.benchmark_daily(
                        self._schemas.benchmark,
                        open_dates,
                        self._benchmark_code,
                    )
                case DatasetComponent.UNIVERSE:
                    evidence = self._pit_component(
                        component,
                        EvidenceCollection.UNIVERSE,
                        self._schemas.universe.manifest_id,
                        request.end_date,
                    )
                case DatasetComponent.FINANCIALS:
                    evidence = self._financial.component(
                        self._schemas.financial_indicators,
                        request.end_date,
                    )
                case DatasetComponent.INDUSTRY:
                    evidence = self._pit_component(
                        component,
                        EvidenceCollection.INDUSTRY_MEMBERSHIPS,
                        self._schemas.industry.manifest_id,
                        request.end_date,
                    )
                case DatasetComponent.BENCHMARK_WEIGHTS:
                    evidence = ComponentCoverage(
                        component=component,
                        start_date=None,
                        end_date=None,
                        schema_manifest_ids=(),
                        source_snapshot_ids=(),
                        lineage_edge_ids=(),
                        quality_passed=False,
                        point_in_time=False,
                        blockers=("component_not_implemented",),
                    )
            components.append(evidence)
        return tuple(components)

    def _pit_component(
        self,
        component: DatasetComponent,
        collection: EvidenceCollection,
        schema_manifest_id: str,
        requested_end: date,
    ) -> ComponentCoverage:
        audit = self._pit.audit_collection(collection, schema_manifest_id)
        bounds = self._date_bounds(collection, schema_manifest_id)
        blockers = list(audit.blockers)
        if bounds is None:
            blockers.append("missing_date_coverage")
        start = _aware_date(bounds.start) if bounds is not None else None
        observed_end = _aware_date(bounds.end) if bounds is not None else None
        end = min(observed_end, requested_end) if observed_end is not None else None
        return _component_from_audit(component, audit, start, end, tuple(sorted(set(blockers))))

    def _date_bounds(
        self,
        collection: EvidenceCollection,
        schema_manifest_id: str,
    ) -> _DateBounds | None:
        documents = tuple(
            self._database[collection.value].aggregate(
                [
                    {
                        "$match": {
                            "schema_manifest_id": schema_manifest_id,
                            "quality_status": "ACCEPTED",
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "start": {"$min": "$available_at"},
                            "end": {"$max": "$available_at"},
                        }
                    },
                ]
            )
        )
        return _DateBounds.model_validate(documents[0]) if documents else None


def _component_from_audit(
    component: DatasetComponent,
    audit: ArtifactEvidenceAudit,
    start: date | None,
    end: date | None,
    blockers: tuple[str, ...],
) -> ComponentCoverage:
    return ComponentCoverage(
        component,
        start,
        end,
        audit.schema_manifest_ids,
        audit.source_snapshot_ids,
        audit.lineage_edge_ids,
        audit.quality_passed,
        audit.point_in_time,
        blockers,
    )


def _aware_date(value: datetime) -> date:
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.date()
