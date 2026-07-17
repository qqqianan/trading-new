from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.industry_memberships import (
    build_industry_membership,
    validate_industry_membership_batch,
)
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_industry_membership_separates_effective_interval_from_knowledge_time() -> None:
    # Given: a historical interval first observed in the current snapshot.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")
    schema = registry.endpoint("index_member")
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    values = (("801010.SI", "000592.SZ", "20211213", "20230701", "N"),)
    raw = build_raw_snapshot(
        TushareQuery("index_member", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    record = canonicalize_batch(raw, schema, registry.manifest_id).records[0]

    # When: the quarantined row is projected into PIT.
    membership = build_industry_membership(record)

    # Then: economic dates and the no-hindsight knowledge clock remain distinct.
    assert membership.quality_status == "ACCEPTED"
    assert membership.index_code == "801010.SI"
    assert membership.con_code == "000592.SZ"
    assert membership.effective_from == datetime(2021, 12, 13, tzinfo=SHANGHAI)
    assert membership.effective_to == datetime(2023, 7, 1, tzinfo=SHANGHAI)
    assert membership.available_at == observed


def test_industry_membership_rejects_reversed_interval() -> None:
    # Given: a provider interval whose exit predates entry.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")
    schema = registry.endpoint("index_member")
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    values = (("801010.SI", "000592.SZ", "20230701", "20211213", "N"),)
    raw = build_raw_snapshot(
        TushareQuery("index_member", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    canonical = canonicalize_batch(raw, schema, registry.manifest_id)

    # When / Then: invalid history cannot become an accepted PIT interval.
    with pytest.raises(SchemaContractError, match="ends before"):
        validate_industry_membership_batch(canonical)
