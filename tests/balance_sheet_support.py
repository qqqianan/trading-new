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
    return SchemaRegistry.load(ROOT / "schemas" / "tushare_balance_sheet_v1.json")


def canonical_batch() -> CanonicalBatch:
    schema_registry = registry()
    schema = schema_registry.endpoint("balancesheet")
    values = (
        "000001.SZ",
        "20260320",
        "20260322",
        "20251231",
        "1",
        "1",
        "4",
        100.0,
        10.0,
        20.0,
        30.0,
        40.0,
        50.0,
        60.0,
        70.0,
        80.0,
        90.0,
        100.0,
        110.0,
        120.0,
        130.0,
        140.0,
        150.0,
        160.0,
        170.0,
        180.0,
        "1",
    )
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        TushareQuery("balancesheet", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        schema_registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    return canonicalize_batch(raw, schema, schema_registry.manifest_id)


def canonical_record() -> CanonicalRecord:
    return canonical_batch().records[0]


def sync_result() -> SyncResult:
    batch = canonical_batch()
    schema_registry = registry()
    schema = schema_registry.endpoint("balancesheet")
    values = tuple(value for _, value in batch.records[0].business_fields)
    observed = batch.records[0].ingested_at
    raw = build_raw_snapshot(
        TushareQuery("balancesheet", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        schema_registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    stored = StoredSnapshot(raw.snapshot.snapshot_id, 1, inserted=True)
    return SyncResult(stored, raw)
