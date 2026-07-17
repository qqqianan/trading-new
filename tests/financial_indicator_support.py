from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def registry() -> SchemaRegistry:
    return SchemaRegistry.load(ROOT / "schemas" / "tushare_financial_indicator_v1.json")


def raw_result() -> SyncResult:
    registered = registry()
    schema = registered.endpoint("fina_indicator")
    metrics = tuple(float(number) for number in range(1, 36))
    values = ("000001.SZ", "20260322", "20251231", *metrics, "1")
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    batch = build_raw_snapshot(
        TushareQuery("fina_indicator", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registered.manifest_id,
        SnapshotTiming(observed, observed),
    )
    return SyncResult(StoredSnapshot(batch.snapshot.snapshot_id, 1, inserted=True), batch)
