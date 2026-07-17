from datetime import UTC, date, datetime
from pathlib import Path

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.research.datasets.batch_coverage import GovernedBatchEvidence
from ashare_lab.research.datasets.coverage import (
    ComponentCoverage,
    CoverageRequest,
    DatasetComponent,
)
from ashare_lab.research.datasets.evidence import ArtifactEvidenceAudit
from ashare_lab.research.datasets.mongo_coverage import (
    CoverageSchemas,
    MongoCoverageEvidenceReader,
)
from ashare_lab.research.datasets.mongo_evidence import EvidenceCollection
from ashare_lab.research.datasets.mongo_financial_coverage import MongoFinancialCoverageReader

ROOT = Path(__file__).parents[1]


class _Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self._documents = documents

    def find(
        self,
        _query: BsonDocument,
        _projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        return self._documents

    def aggregate(self, _pipeline: list[BsonDocument]) -> tuple[BsonDocument, ...]:
        return self._documents


class _Database:
    name = "ashare_quant"

    def __init__(self, documents: dict[str, tuple[BsonDocument, ...]]) -> None:
        self._documents = documents

    def __getitem__(self, collection: str) -> _Collection:
        return _Collection(self._documents.get(collection, ()))


class _BatchReader:
    def batch_evidence(
        self,
        snapshot_ids: tuple[str, ...],
        schema_manifest_id: str,
    ) -> tuple[GovernedBatchEvidence, ...]:
        return tuple(
            GovernedBatchEvidence(
                snapshot_id=snapshot_id,
                endpoint="fina_indicator",
                schema_manifest_id=schema_manifest_id,
                status="ACCEPTED",
                versioned_lineage_edge_ids=(f"canonical_lineage_{snapshot_id}",),
                qualified_lineage_edge_ids=(),
                quality_evidenced_artifact_ids=(f"canonical_{snapshot_id}",),
            )
            for snapshot_id in snapshot_ids
        )


class _EventReader:
    @staticmethod
    def audit_collection(
        collection: EvidenceCollection,
        schema_manifest_id: str,
    ) -> ArtifactEvidenceAudit:
        del collection
        return ArtifactEvidenceAudit(
            schema_manifest_ids=(schema_manifest_id,),
            source_snapshot_ids=("snap_financial",),
            lineage_edge_ids=("event_lineage",),
            quality_passed=True,
            point_in_time=True,
            blockers=(),
        )


class _MatrixBatchReader:
    @staticmethod
    def market_daily(
        registry: SchemaRegistry,
        start_date: date,
        end_date: date,
    ) -> tuple[ComponentCoverage, tuple[date, ...]]:
        del registry
        return (
            _component(DatasetComponent.MARKET_DAILY, start_date, end_date),
            (start_date, end_date),
        )

    @staticmethod
    def benchmark_daily(
        registry: SchemaRegistry,
        required_dates: tuple[date, ...],
        benchmark_code: str,
    ) -> ComponentCoverage:
        del registry, benchmark_code
        return _component(
            DatasetComponent.BENCHMARK_DAILY,
            min(required_dates),
            max(required_dates),
        )


class _MatrixPitReader:
    @staticmethod
    def audit_collection(
        collection: EvidenceCollection,
        schema_manifest_id: str,
    ) -> ArtifactEvidenceAudit:
        del collection
        return ArtifactEvidenceAudit(
            schema_manifest_ids=(schema_manifest_id,),
            source_snapshot_ids=("snap_pit",),
            lineage_edge_ids=("lineage_pit",),
            quality_passed=True,
            point_in_time=True,
            blockers=(),
        )


class _MatrixFinancialReader:
    @staticmethod
    def component(registry: SchemaRegistry, requested_end: date) -> ComponentCoverage:
        del registry
        return _component(DatasetComponent.FINANCIALS, date(2020, 1, 1), requested_end)


def _component(name: DatasetComponent, start: date, end: date) -> ComponentCoverage:
    return ComponentCoverage(
        component=name,
        start_date=start,
        end_date=end,
        schema_manifest_ids=(f"schema_{name.value}",),
        source_snapshot_ids=(f"snap_{name.value}",),
        lineage_edge_ids=(f"lineage_{name.value}",),
        quality_passed=True,
        point_in_time=True,
    )


def _schemas() -> CoverageSchemas:
    return CoverageSchemas(
        SchemaRegistry.load(ROOT / "schemas" / "tushare_p0_v1.json"),
        SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json"),
        SchemaRegistry.load(ROOT / "schemas" / "tushare_universe_v1.json"),
        SchemaRegistry.load(ROOT / "schemas" / "tushare_financial_indicator_v1.json"),
        SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json"),
    )


def test_financial_reader_accepts_quarantined_canonical_then_passed_pit_batch() -> None:
    # Given: a range request with canonical quarantine evidence and passed PIT batch evidence.
    schema = _schemas().financial_indicators
    database = _Database(
        {
            "meta_source_snapshots": (
                {
                    "snapshot_id": "snap_financial",
                    "request_params_canonical": (
                        '{"start_date":"20200101","end_date":"20260716","ts_code":"000001.SZ"}'
                    ),
                },
            ),
            "meta_lineage_edges": (
                {
                    "lineage_edge_id": "pit_batch_lineage",
                    "upstream_artifact_id": "canonical_snap_financial",
                    "downstream_artifact_id": "pit_batch_financial",
                    "code_commit": "a" * 40,
                },
            ),
            "meta_quality_reports": ({"artifact_id": "pit_batch_financial", "passed": True},),
        }
    )
    reader = MongoFinancialCoverageReader.__new__(MongoFinancialCoverageReader)
    reader.__dict__["_database"] = database
    reader.__dict__["_batch_reader"] = _BatchReader()
    reader.__dict__["_events"] = _EventReader()

    # When: the full two-hop financial chain is audited.
    coverage = reader.component(schema, date(2026, 7, 16))

    # Then: zero-event range coverage begins at the Raw request, not first announcement.
    assert coverage.start_date == date(2020, 1, 1)
    assert coverage.end_date == date(2026, 7, 16)
    assert coverage.blockers == ()
    assert "pit_batch_lineage" in coverage.lineage_edge_ids


def test_unified_reader_routes_all_closed_component_variants() -> None:
    # Given: fixed readers and date bounds for every closed component variant.
    bounds = (
        {
            "start": datetime(1990, 12, 1, tzinfo=UTC),
            "end": datetime(2026, 7, 17, tzinfo=UTC),
        },
    )
    database = _Database(
        {
            "pit_security_events": bounds,
            "pit_industry_memberships": bounds,
        }
    )
    reader = MongoCoverageEvidenceReader.__new__(MongoCoverageEvidenceReader)
    reader.__dict__["_database"] = database
    reader.__dict__["_schemas"] = _schemas()
    reader.__dict__["_benchmark_code"] = "000905.SH"
    reader.__dict__["_batch"] = _MatrixBatchReader()
    reader.__dict__["_pit"] = _MatrixPitReader()
    reader.__dict__["_financial"] = _MatrixFinancialReader()
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2026, 7, 16),
        tuple(DatasetComponent),
    )

    # When: the unified matrix routes every requested component.
    components = reader.components(request)

    # Then: implemented components carry evidence and weights fail closed explicitly.
    by_name = {item.component: item for item in components}
    assert len(by_name) == len(DatasetComponent)
    assert by_name[DatasetComponent.INDUSTRY].end_date == date(2026, 7, 16)
    assert by_name[DatasetComponent.BENCHMARK_WEIGHTS].blockers == ("component_not_implemented",)
