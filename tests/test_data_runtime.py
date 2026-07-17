from pathlib import Path

import pytest

from ashare_lab.data import queries
from ashare_lab.data.config import DataSettings
from ashare_lab.data.http_client import create_provider_client
from ashare_lab.data.mongo_store import MongoRawStore, StoredSnapshot
from ashare_lab.data.queries import (
    calendar_query,
    daily_queries,
    name_history_queries,
    security_master_queries,
)
from ashare_lab.data.schema_registry import EndpointSchema, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotBatch
from ashare_lab.data.sync_service import RequestPacer, TushareSyncService
from ashare_lab.data.tushare_client import TushareClient, TushareQuery, TushareTable

PROJECT_ROOT = Path(__file__).parents[1]


class StaticTushareClient(TushareClient):
    """Return one committed adjustment-factor row without network access."""

    def __init__(self, fields: tuple[str, ...]) -> None:
        self._fields = fields

    def fetch(self, query: TushareQuery) -> TushareTable:
        assert query.fields == self._fields
        return self.table_for_test(
            fields=self._fields,
            rows=(("000001.SZ", "20260710", 124.532),),
        )


class RecordingRawStore(MongoRawStore):
    """Capture a validated batch without requiring an external database."""

    def __init__(self) -> None:
        self.endpoint = ""
        self.row_count = 0

    def write_batch(self, schema: EndpointSchema, batch: SnapshotBatch) -> StoredSnapshot:
        assert schema.raw_collection.startswith("raw_tushare_")
        self.endpoint = batch.snapshot.endpoint
        self.row_count = len(batch.rows)
        return StoredSnapshot(batch.snapshot.snapshot_id, len(batch.rows), inserted=True)


def _registry() -> SchemaRegistry:
    return SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")


def test_query_builders_pin_all_pilot_parameters_and_fields() -> None:
    # Given: the committed P0 registry.
    registry = _registry()

    # When: daily, universe, and calendar jobs are constructed.
    daily = daily_queries(registry, "20260710")
    masters = security_master_queries(registry)
    calendar = calendar_query(registry, "20260701", "20260731")

    # Then: every job remains explicit and schema projected.
    assert tuple(query.endpoint for query in daily) == (
        "daily",
        "adj_factor",
        "daily_basic",
        "stk_limit",
        "suspend_d",
    )
    assert tuple(query.params[-1].value for query in masters) == ("L", "P", "D")
    assert calendar.params[-1].value == "20260731"


def test_name_history_queries_split_closed_range_by_calendar_year() -> None:
    # Given: the independent universe schema and a range spanning three years.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")

    # When: historical name requests are built.
    queries = name_history_queries(registry, "20201215", "20220203")

    # Then: every year is bounded and projected through the committed schema.
    assert tuple(query.params[0].value for query in queries) == (
        "20201215",
        "20210101",
        "20220101",
    )
    assert tuple(query.params[1].value for query in queries) == (
        "20201231",
        "20211231",
        "20220203",
    )
    assert all(query.fields == registry.endpoint("namechange").field_names for query in queries)


def test_dividend_queries_cover_every_announcement_calendar_date() -> None:
    # Given: a dividend range spanning a weekend under its isolated schema.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_corporate_actions_v1.json")

    # When: historical announcement requests are constructed.
    built = queries.dividend_announcement_queries(registry, "20260710", "20260712")

    # Then: every calendar date is explicit, bounded, and schema projected.
    assert tuple(query.params[0].name for query in built) == ("ann_date",) * 3
    assert tuple(query.params[0].value for query in built) == (
        "20260710",
        "20260711",
        "20260712",
    )
    assert all(query.fields == registry.endpoint("dividend").field_names for query in built)


def test_income_vip_queries_are_partitioned_by_report_period() -> None:
    # Given: two closed report periods under the financial schema.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_financials_v1.json")

    # When: full-market income requests are built.
    built = queries.income_period_queries(registry, ("20250331", "20250630"))

    # Then: every query is period-bounded and uses the committed VIP projection.
    assert tuple(query.endpoint for query in built) == ("income_vip", "income_vip")
    assert tuple(query.params[0].value for query in built) == ("20250331", "20250630")
    assert all(query.fields == registry.endpoint("income_vip").field_names for query in built)


def test_income_security_queries_pin_code_and_announcement_range() -> None:
    # Given: two historical lifecycle codes and one closed announcement range.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_financials_v1.json")

    # When: standard income requests are constructed.
    built = queries.income_security_queries(
        registry,
        ("000001.SZ", "600000.SH"),
        "20200101",
        "20260716",
    )

    # Then: each code receives one explicit, schema-projected range request.
    assert tuple(query.endpoint for query in built) == ("income", "income")
    assert tuple(query.params[0].value for query in built) == ("000001.SZ", "600000.SH")
    assert tuple(param.value for param in built[0].params[1:]) == (
        "20200101",
        "20260716",
    )


def test_settings_build_isolated_uri_without_changing_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: environment-only credentials for the isolated database.
    monkeypatch.setenv("TUSHARE_TOKEN", "unit")
    monkeypatch.setenv("MONGODB_USERNAME", "reader")
    monkeypatch.setenv("MONGODB_PASSWORD", "p@ss")
    monkeypatch.setenv("MONGODB_DATABASE", "ashare_quant")
    monkeypatch.chdir(PROJECT_ROOT / "tests")

    # When: settings create the MongoDB connection URI.
    settings = DataSettings()

    # Then: credentials are encoded and the database cannot drift to the legacy source.
    assert "reader:p%40ss" in settings.mongodb_uri
    assert "/ashare_quant?" in settings.mongodb_uri


def test_http_factory_returns_an_explicit_owned_client() -> None:
    # Given / When: the provider client factory is used.
    client = create_provider_client()

    # Then: callers can deterministically release its resources.
    assert client.is_closed is False
    client.close()
    assert client.is_closed is True


def test_sync_service_validates_before_calling_store() -> None:
    # Given: a registered query, static provider, and recording store.
    registry = _registry()
    schema = registry.endpoint("adj_factor")
    query = daily_queries(registry, "20260710")[1]
    store = RecordingRawStore()
    service = TushareSyncService(
        registry,
        StaticTushareClient(schema.field_names),
        store,
        RequestPacer(0.0, lambda _seconds: None),
    )

    # When: one endpoint is synchronized.
    result = service.sync(query)

    # Then: the store receives a schema-valid, content-addressed batch.
    assert result.inserted is True
    assert result.snapshot_id.startswith("snap_")
    assert result.row_count == 1
    assert store.endpoint == "adj_factor"
    assert store.row_count == 1


def test_sync_service_paces_every_provider_request() -> None:
    # Given: an injected pacer that records waits without using wall-clock time.
    registry = _registry()
    schema = registry.endpoint("adj_factor")
    waits: list[float] = []
    service = TushareSyncService(
        registry,
        StaticTushareClient(schema.field_names),
        RecordingRawStore(),
        RequestPacer(1.2, waits.append),
    )

    # When: one provider request crosses the service boundary.
    service.sync(daily_queries(registry, "20260710")[1])

    # Then: the configured minimum interval is enforced before the request.
    assert waits == [1.2]
