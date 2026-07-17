from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.mongo_schema import MongoSchemaBuilder
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_industry_schema_quarantines_membership_until_observed_pit_projection() -> None:
    # Given: the committed SW2021 industry schema.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")

    # When: strict Raw and canonical validators are generated.
    plan = MongoSchemaBuilder(registry).collection_plan()
    member = registry.endpoint("index_member")

    # Then: historical interval fields remain explicit and nullable where truthful.
    assert registry.schema_version == "1.0.1"
    assert registry.endpoint_names == ("index_classify", "index_member")
    assert member.available_at_policy == "observed_membership_snapshot"
    assert "pit_industry_memberships" in plan
    payload = plan[member.raw_collection].root.property("payload")
    assert "out_date" not in payload.required
    assert "null" in payload.property("out_date").bson_types


def test_industry_member_historical_dates_do_not_backdate_availability() -> None:
    # Given: a historical membership first observed by this system today.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")
    schema = registry.endpoint("index_member")
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    values = (
        (
            "801010.SI",
            "000592.SZ",
            "20211213",
            None,
            "Y",
        ),
    )

    # When: the provider row crosses Raw and canonical governance.
    raw = build_raw_snapshot(
        TushareQuery("index_member", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)

    # Then: the interval stays auditable but cannot be read before observation.
    record = canonical.records[0]
    assert canonical.quality_status == "QUARANTINED"
    assert record.event_time == observed
    assert record.available_at == observed
    assert dict(record.business_fields)["in_date"] == "20211213"
