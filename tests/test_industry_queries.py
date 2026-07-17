from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.industry_queries import (
    INDUSTRY_SOURCE,
    industry_master_query,
    industry_member_queries,
    level_one_industry_codes,
)
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_industry_queries_pin_source_and_exact_level_one_codes() -> None:
    # Given: the committed industry schema and unordered duplicated L1 codes.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")

    # When: taxonomy and exact membership requests are built.
    master = industry_master_query(registry)
    members = industry_member_queries(
        registry,
        ("801020.SI", "801010.SI", "801010.SI"),
    )

    # Then: source, projections, ordering, and exact request boundaries are stable.
    assert INDUSTRY_SOURCE == "SW2021"
    assert master.endpoint == "index_classify"
    assert tuple((param.name, param.value) for param in master.params) == (("src", "SW2021"),)
    assert tuple(query.params[0].value for query in members) == (
        "801010.SI",
        "801020.SI",
    )
    assert all(
        query.fields == registry.endpoint(query.endpoint).field_names
        for query in (master, *members)
    )


def test_level_one_codes_come_only_from_governed_sw2021_rows() -> None:
    # Given: mixed taxonomy levels in one accepted provider response.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")
    schema = registry.endpoint("index_classify")
    query = industry_master_query(registry)
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    values = (
        ("801020.SI", "采掘", "L1", "110000", "Y", None, "SW2021"),
        ("801010.SI", "农林牧渔", "L1", "110000", "Y", None, "SW2021"),
        ("801011.SI", "林业Ⅱ", "L2", "110100", "Y", "801010.SI", "SW2021"),
    )
    batch = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When: executable member boundaries are derived.
    codes = level_one_industry_codes(batch)

    # Then: only deterministic level-one identities are returned.
    assert codes == ("801010.SI", "801020.SI")


def test_level_one_code_extraction_fails_closed_on_source_drift() -> None:
    # Given: a provider row from an unapproved taxonomy source.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")
    schema = registry.endpoint("index_classify")
    query = industry_master_query(registry)
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    values = (("801010.SI", "农林牧渔", "L1", "110000", "Y", None, "SW2014"),)
    batch = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When / Then: an unapproved source cannot drive member requests.
    with pytest.raises(SchemaContractError, match="unexpected source"):
        level_one_industry_codes(batch)


def test_level_one_code_extraction_rejects_empty_taxonomy() -> None:
    # Given: an accepted empty taxonomy response.
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_industry_v1.json")
    schema = registry.endpoint("index_classify")
    query = industry_master_query(registry)
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    batch = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, ()),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )

    # When / Then: empty master data cannot be mistaken for a complete universe.
    with pytest.raises(SchemaContractError, match="no level-one codes"):
        level_one_industry_codes(batch)
