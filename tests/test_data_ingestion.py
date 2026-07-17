from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
import pytest

from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import (
    QueryParam,
    TushareApiError,
    TushareClient,
    TushareQuery,
)

PROJECT_ROOT = Path(__file__).parents[1]


def test_schema_registry_loads_versioned_p0_contracts() -> None:
    # Given: the committed machine-readable P0 schema bundle.
    path = PROJECT_ROOT / "schemas" / "tushare_p0_v1.json"

    # When: the bundle crosses the file boundary.
    registry = SchemaRegistry.load(path)

    # Then: its identity and endpoint coverage are deterministic.
    assert registry.manifest_id.startswith("schema_")
    assert registry.database == "ashare_quant"
    assert registry.endpoint_names == (
        "adj_factor",
        "daily",
        "daily_basic",
        "stk_limit",
        "stock_basic",
        "suspend_d",
        "trade_cal",
    )
    assert registry.endpoint("daily").field_names[-2:] == ("vol", "amount")
    stock_market = next(
        field for field in registry.endpoint("stock_basic").fields if field[0] == "market"
    )
    assert stock_market[2] is True


def test_corporate_action_schema_documents_complete_dividend_contract() -> None:
    # Given: the committed corporate-action schema bundle.
    path = PROJECT_ROOT / "schemas" / "tushare_corporate_actions_v1.json"

    # When: the bundle crosses the file boundary.
    registry = SchemaRegistry.load(path)

    # Then: dividend lifecycle and implementation fields are closed and explicit.
    dividend = registry.endpoint("dividend")
    assert registry.endpoint_names == ("dividend",)
    assert dividend.natural_key == (
        "ts_code",
        "end_date",
        "ann_date",
        "div_proc",
        "imp_ann_date",
    )
    assert dividend.field_names == (
        "ts_code",
        "end_date",
        "ann_date",
        "div_proc",
        "stk_div",
        "stk_bo_rate",
        "stk_co_rate",
        "cash_div",
        "cash_div_tax",
        "record_date",
        "ex_date",
        "pay_date",
        "div_listdate",
        "imp_ann_date",
        "base_date",
        "base_share",
    )


def test_financial_schema_documents_income_and_vip_source_contracts() -> None:
    # Given: the committed first financial-statement schema bundle.
    path = PROJECT_ROOT / "schemas" / "tushare_financials_v1.json"

    # When: the bundle crosses the file boundary.
    registry = SchemaRegistry.load(path)

    # Then: standard and full-market sources share one closed field projection.
    assert registry.endpoint_names == ("income", "income_vip")
    standard = registry.endpoint("income")
    vip = registry.endpoint("income_vip")
    assert standard.field_names == vip.field_names
    assert standard.field_names == (
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "end_type",
        "basic_eps",
        "diluted_eps",
        "total_revenue",
        "revenue",
        "operate_profit",
        "total_profit",
        "income_tax",
        "n_income",
        "n_income_attr_p",
        "ebit",
        "ebitda",
        "rd_exp",
        "update_flag",
    )


def test_tushare_client_parses_provider_table_without_exposing_token() -> None:
    # Given: a wire-level Tushare response and an injected HTTP transport.
    def respond(request: httpx2.Request) -> httpx2.Response:
        assert query.endpoint in request.content.decode()
        return httpx2.Response(
            200,
            json={
                "request_id": "req-1",
                "code": 0,
                "msg": None,
                "data": {
                    "fields": ["ts_code", "trade_date", "close"],
                    "items": [["000001.SZ", "20260710", 10.24]],
                },
            },
        )

    transport = httpx2.MockTransport(respond)
    query = TushareQuery(
        endpoint="daily",
        params=(QueryParam(name="trade_date", value="20260710"),),
        fields=("ts_code", "trade_date", "close"),
    )

    # When: the client calls the provider through the real HTTP boundary.
    with httpx2.Client(transport=transport) as http_client:
        table = TushareClient(token=query.endpoint, http_client=http_client).fetch(query)

    # Then: provider columns and typed scalar values are preserved.
    assert table.fields == query.fields
    assert table.rows[0].values == ("000001.SZ", "20260710", 10.24)


def test_snapshot_builder_rejects_fields_outside_committed_schema() -> None:
    # Given: a provider table whose requested fields omit most daily columns.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    query = TushareQuery(
        endpoint="daily",
        params=(QueryParam(name="trade_date", value="20260710"),),
        fields=("ts_code", "trade_date", "close"),
    )
    now = datetime(2026, 7, 14, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    # When / Then: Raw cannot be accepted under an incomplete field contract.
    with pytest.raises(SchemaContractError, match="field contract"):
        build_raw_snapshot(
            query=query,
            table=TushareClient.table_for_test(
                fields=query.fields,
                rows=(("000001.SZ", "20260710", 10.24),),
            ),
            endpoint_schema=registry.endpoint("daily"),
            schema_manifest_id=registry.manifest_id,
            timing=SnapshotTiming(requested_at=now, completed_at=now),
        )


def test_snapshot_identity_is_stable_for_identical_provider_payload() -> None:
    # Given: the complete adjustment-factor contract and one provider row.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    schema = registry.endpoint("adj_factor")
    query = TushareQuery(
        endpoint="adj_factor",
        params=(QueryParam(name="trade_date", value="20260710"),),
        fields=schema.field_names,
    )
    table = TushareClient.table_for_test(
        fields=schema.field_names,
        rows=(("000001.SZ", "20260710", 124.532),),
    )
    now = datetime(2026, 7, 14, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    # When: the same response is materialized twice.
    timing = SnapshotTiming(requested_at=now, completed_at=now)
    first = build_raw_snapshot(query, table, schema, registry.manifest_id, timing)
    second = build_raw_snapshot(query, table, schema, registry.manifest_id, timing)

    # Then: content identity and row hashes are reproducible.
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.rows == second.rows
    assert first.snapshot.row_count == 1


def test_unregistered_endpoint_and_provider_error_fail_closed() -> None:
    # Given: a committed registry and a provider error response.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")

    def reject(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        return httpx2.Response(200, json={"code": 2002, "msg": "permission denied", "data": None})

    query = TushareQuery(endpoint="daily", params=(), fields=("ts_code",))

    # When / Then: neither unknown schemas nor rejected API calls can produce Raw.
    with pytest.raises(SchemaContractError, match="not registered"):
        registry.endpoint("unknown_endpoint")
    with (
        httpx2.Client(transport=httpx2.MockTransport(reject)) as http_client,
        pytest.raises(TushareApiError, match="permission denied"),
    ):
        TushareClient(token=query.endpoint, http_client=http_client).fetch(query)


def test_snapshot_builder_rejects_provider_row_width_mismatch() -> None:
    # Given: a complete schema projection with a truncated provider row.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    schema = registry.endpoint("adj_factor")
    query = TushareQuery(endpoint="adj_factor", params=(), fields=schema.field_names)
    table = TushareClient.table_for_test(fields=schema.field_names, rows=(("000001.SZ",),))
    now = datetime(2026, 7, 14, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    # When / Then: an incomplete provider row is rejected before hashing or storage.
    with pytest.raises(SchemaContractError, match="row width"):
        build_raw_snapshot(
            query,
            table,
            schema,
            registry.manifest_id,
            SnapshotTiming(now, now),
        )
