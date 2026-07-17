from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.canonical import CanonicalBatch, CanonicalRecord, canonicalize_batch
from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def registry() -> SchemaRegistry:
    return SchemaRegistry.load(ROOT / "schemas" / "tushare_cashflow_v1.json")


def raw_result() -> SyncResult:
    schema_registry = registry()
    schema = schema_registry.endpoint("cashflow")
    metrics = tuple(float(number) for number in range(1, 27))
    values = (
        "000001.SZ",
        "20260320",
        "20260322",
        "20251231",
        "1",
        "1",
        "4",
        *metrics,
        "1",
    )
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        TushareQuery("cashflow", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        schema_registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    return SyncResult(
        StoredSnapshot(raw.snapshot.snapshot_id, 1, inserted=True),
        raw,
    )


def canonical_batch() -> CanonicalBatch:
    result = raw_result()
    schema_registry = registry()
    return canonicalize_batch(
        result.batch,
        schema_registry.endpoint("cashflow"),
        schema_registry.manifest_id,
    )


def canonical_record() -> CanonicalRecord:
    return canonical_batch().records[0]
