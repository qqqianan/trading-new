from datetime import date
from pathlib import Path

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.research.datasets.mongo_batch_coverage import MongoBatchCoverageReader

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


class _Database:
    name = "ashare_quant"

    def __init__(self, documents: dict[str, tuple[BsonDocument, ...]]) -> None:
        self._documents = documents

    def __getitem__(self, collection: str) -> _Collection:
        return _Collection(self._documents.get(collection, ()))


def test_mongo_market_reader_requires_calendar_and_all_five_daily_batches() -> None:
    # Given: one open date with accepted, versioned, quality-passed evidence for six endpoints.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_p0_v1.json")
    endpoints = ("trade_cal", "daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d")
    snapshots = tuple(
        {
            "snapshot_id": f"snap_{endpoint}",
            "endpoint": endpoint,
            "request_params_canonical": (
                '{"start_date":"20200102","end_date":"20200102"}'
                if endpoint == "trade_cal"
                else '{"trade_date":"20200102"}'
            ),
            "schema_manifest_id": registry.manifest_id,
            "status": "ACCEPTED",
        }
        for endpoint in endpoints
    )
    lineage = tuple(
        {
            "lineage_edge_id": f"lineage_{endpoint}",
            "upstream_artifact_id": f"snap_{endpoint}",
            "downstream_artifact_id": f"canonical_{endpoint}",
            "output_schema_id": registry.manifest_id,
            "transform_name": "tushare_raw_to_canonical",
            "code_commit": "a" * 40,
        }
        for endpoint in endpoints
    )
    quality = tuple(
        {"artifact_id": f"canonical_{endpoint}", "passed": True} for endpoint in endpoints
    )
    database = _Database(
        {
            "canonical_trade_calendar": (
                {
                    "cal_date": "20200102",
                    "exchange": "SSE",
                    "is_open": 1,
                    "source_snapshot_id": "snap_trade_cal",
                    "schema_manifest_id": registry.manifest_id,
                    "quality_status": "ACCEPTED",
                },
            ),
            "meta_source_snapshots": snapshots,
            "meta_lineage_edges": lineage,
            "meta_quality_reports": quality,
        }
    )

    # When: the production Mongo adapter audits the requested market interval.
    coverage, open_dates = MongoBatchCoverageReader(database).market_daily(
        registry,
        date(2020, 1, 2),
        date(2020, 1, 2),
    )

    # Then: the component pins all six Raw and lineage identities with no blocker.
    assert open_dates == (date(2020, 1, 2),)
    assert len(coverage.source_snapshot_ids) == 6
    assert coverage.blockers == ()


def test_mongo_benchmark_reader_uses_the_market_schedule() -> None:
    # Given: one accepted benchmark row with a versioned, quality-passed batch chain.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")
    database = _Database(
        {
            "canonical_index_daily_bar": (
                {
                    "trade_date": "20200102",
                    "source_snapshot_id": "snap_index_daily",
                },
            ),
            "meta_source_snapshots": (
                {
                    "snapshot_id": "snap_index_daily",
                    "endpoint": "index_daily",
                    "request_params_canonical": '{"trade_date":"20200102"}',
                    "schema_manifest_id": registry.manifest_id,
                    "status": "ACCEPTED",
                },
            ),
            "meta_lineage_edges": (
                {
                    "lineage_edge_id": "lineage_index_daily",
                    "upstream_artifact_id": "snap_index_daily",
                    "downstream_artifact_id": "canonical_index_daily",
                    "code_commit": "a" * 40,
                },
            ),
            "meta_quality_reports": ({"artifact_id": "canonical_index_daily", "passed": True},),
        }
    )

    # When: benchmark coverage is audited against the market's open-date schedule.
    coverage = MongoBatchCoverageReader(database).benchmark_daily(
        registry,
        (date(2020, 1, 2),),
        "000905.SH",
    )

    # Then: the exact benchmark batch qualifies without an envelope-only shortcut.
    assert coverage.start_date == date(2020, 1, 2)
    assert coverage.end_date == date(2020, 1, 2)
    assert coverage.blockers == ()


def test_mongo_benchmark_reader_blocks_an_empty_market_schedule() -> None:
    # Given: a valid registry but no qualified market dates.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")

    # When: benchmark coverage is requested without a market schedule.
    coverage = MongoBatchCoverageReader(_Database({})).benchmark_daily(
        registry,
        (),
        "000905.SH",
    )

    # Then: no benchmark interval can be inferred from an envelope or current row.
    assert coverage.start_date is None
    assert coverage.blockers == ("empty_scheduled_dates",)
