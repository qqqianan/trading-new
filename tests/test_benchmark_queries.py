from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.benchmark_queries import (
    BENCHMARK_CODES,
    benchmark_daily_queries,
    benchmark_master_queries,
    benchmark_weight_queries,
)
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.mongo_schema import MongoSchemaBuilder
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_benchmark_queries_pin_six_indices_and_schema_fields() -> None:
    # Given: the committed benchmark schema and one historical range.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")

    # When: master, daily, and monthly-weight requests are built.
    masters = benchmark_master_queries(registry)
    daily = benchmark_daily_queries(registry, "20200101", "20260716")
    weights = benchmark_weight_queries(registry, "20200101", "20200229")

    # Then: benchmark identity, time bounds, and provider projections are explicit.
    assert len(BENCHMARK_CODES) == 6
    assert tuple(query.params[0].value for query in daily) == BENCHMARK_CODES
    assert tuple(query.params[0].value for query in weights[:2]) == ("000300.SH", "000300.SH")
    assert tuple(query.params[0].value for query in masters) == BENCHMARK_CODES
    assert tuple(query.endpoint for query in masters) == ("index_basic",) * len(masters)
    assert all(
        query.fields == registry.endpoint(query.endpoint).field_names
        for query in (*masters, *daily, *weights)
    )


def test_index_daily_accepts_base_date_with_only_close_price() -> None:
    # Given: the provider's real Beijing 50 base-date shape.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")
    schema = registry.endpoint("index_daily")
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    values = (
        (
            "899050.BJ",
            "20220429",
            1000.0,
            None,
            None,
            None,
            None,
            None,
            None,
            455215.5,
            581906.406,
        ),
    )

    # When: the governed Raw and canonical transformations run.
    raw = build_raw_snapshot(
        TushareQuery("index_daily", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)
    payload_rule = MongoSchemaBuilder(registry).raw_validator(schema).root.property("payload")

    # Then: missing OHLC remains null while close and PIT timing stay truthful.
    record = canonical.records[0]
    fields = dict(record.business_fields)
    assert canonical.quality_status == "ACCEPTED"
    assert fields["close"] == 1000.0
    assert (fields["open"], fields["high"], fields["low"]) == (None, None, None)
    assert all(
        field not in payload_rule.required and "null" in payload_rule.property(field).bson_types
        for field in ("open", "high", "low")
    )
    assert record.available_at == datetime(2022, 4, 29, 16, 0, tzinfo=SHANGHAI)
