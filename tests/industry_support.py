from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.canonical import CanonicalBatch, canonicalize_batch
from ashare_lab.data.industry_queries import industry_master_query
from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def industry_registry() -> SchemaRegistry:
    return SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")


def taxonomy_result() -> SyncResult:
    registry = industry_registry()
    schema = registry.endpoint("index_classify")
    query = industry_master_query(registry)
    values = (("801010.SI", "农林牧渔", "L1", "110000", "Y", None, "SW2021"),)
    return _result(query, schema.field_names, values)


def member_result() -> SyncResult:
    registry = industry_registry()
    schema = registry.endpoint("index_member")
    query = TushareQuery("index_member", (), schema.field_names)
    values = (("801010.SI", "000592.SZ", "20211213", None, "Y"),)
    return _result(query, schema.field_names, values)


def member_canonical() -> CanonicalBatch:
    registry = industry_registry()
    result = member_result()
    return canonicalize_batch(result.batch, registry.endpoint("index_member"), registry.manifest_id)


def _result(
    query: TushareQuery,
    fields: tuple[str, ...],
    values: tuple[tuple[str | None, ...], ...],
) -> SyncResult:
    registry = industry_registry()
    schema = registry.endpoint(query.endpoint)
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(fields, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    return SyncResult(
        StoredSnapshot(raw.snapshot.snapshot_id, len(values), inserted=True),
        raw,
    )
