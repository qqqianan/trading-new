from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.canonical import CanonicalBatch, canonicalize_batch
from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def benchmark_registry() -> SchemaRegistry:
    return SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")


def weight_sync_result() -> SyncResult:
    registry = benchmark_registry()
    schema = registry.endpoint("index_weight")
    values = (
        ("000300.SH", "000001.SZ", "20260331", 60.0),
        ("000300.SH", "600000.SH", "20260331", 40.0),
    )
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        TushareQuery("index_weight", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    return SyncResult(StoredSnapshot(raw.snapshot.snapshot_id, 2, inserted=True), raw)


def weight_canonical() -> CanonicalBatch:
    registry = benchmark_registry()
    result = weight_sync_result()
    return canonicalize_batch(result.batch, registry.endpoint("index_weight"), registry.manifest_id)
