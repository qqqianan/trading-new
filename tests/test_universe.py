from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.canonical import CanonicalRecord, canonicalize_batch
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient, TushareQuery
from ashare_lab.data.universe import (
    SecurityEventType,
    select_security_states,
)
from ashare_lab.data.universe_builder import (
    build_first_trade_event,
    build_lifecycle_events,
    build_name_status_event,
)

PROJECT_ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
OBSERVED = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)


def test_future_delisting_does_not_remove_historically_listed_security() -> None:
    # Given: a current master row containing a delisting one year after listing.
    events = build_lifecycle_events(_master_record())

    # When: the universe is queried before the delisting event becomes effective.
    states = select_security_states(
        events,
        datetime(2020, 6, 1, 15, 30, tzinfo=SHANGHAI),
    )

    # Then: the security is present without exposing its future outcome.
    assert states[0].ts_code == "000001.SZ"
    assert states[0].name is None
    assert states[0].is_st is None


def test_delisting_event_removes_security_only_after_effective_time() -> None:
    # Given: lifecycle events containing an historical delisting.
    events = build_lifecycle_events(_master_record())

    # When: the universe is queried after the delisting date begins.
    states = select_security_states(
        events,
        datetime(2021, 1, 5, 10, 0, tzinfo=SHANGHAI),
    )

    # Then: the delisted security is absent.
    assert states == ()


def test_announced_name_status_waits_until_effective_date() -> None:
    # Given: an ST name announced before it becomes effective.
    events = (*build_lifecycle_events(_master_record()), build_name_status_event(_name_record()))

    # When: queried after announcement but before effective date.
    states = select_security_states(
        events,
        datetime(2020, 4, 30, 19, 0, tzinfo=SHANGHAI),
    )

    # Then: the future ST state remains hidden.
    assert states[0].status_known is False
    assert states[0].is_st is None


def test_effective_name_status_updates_historical_st_state() -> None:
    # Given: listing and historically announced ST-name events.
    events = (*build_lifecycle_events(_master_record()), build_name_status_event(_name_record()))

    # When: queried after both announcement and effective time.
    states = select_security_states(
        events,
        datetime(2020, 5, 1, 10, 0, tzinfo=SHANGHAI),
    )

    # Then: the point-in-time state carries the historical name and ST flag.
    assert states[0].name == "ST平安"
    assert states[0].is_st is True
    assert states[0].status_known is True


def test_universe_query_rejects_naive_decision_time() -> None:
    # Given: valid lifecycle events.
    events = build_lifecycle_events(_master_record())

    # When / Then: a timezone-free decision cannot cross the PIT boundary.
    with pytest.raises(ValueError, match="timezone-aware"):
        select_security_states(events, datetime(2020, 6, 1))  # noqa: DTZ001


def test_future_listing_can_be_known_before_it_becomes_effective() -> None:
    # Given: a stock observed shortly before its official first trading time.
    observed = datetime(2026, 7, 16, 9, 14, tzinfo=SHANGHAI)
    record = _master_record()
    fields = tuple(
        (name, "20260716" if name == "list_date" else value)
        for name, value in record.business_fields
    )
    future_listing = replace(
        record,
        available_at=observed,
        ingested_at=observed,
        business_fields=fields,
    )

    # When: lifecycle facts are converted into independent event clocks.
    listed = build_lifecycle_events(future_listing)[0]

    # Then: knowledge is immediate while membership waits until market effectiveness.
    assert listed.available_at == observed
    assert listed.effective_at == datetime(2026, 7, 16, 9, 25, tzinfo=SHANGHAI)


def test_reobserved_snapshot_cannot_create_a_second_event_identity() -> None:
    # Given: the same content-addressed source row replayed with a later observation clock.
    original = _master_record()
    replayed = replace(
        original,
        available_at=datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI),
        ingested_at=datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI),
    )

    # When: both observations are transformed into current-name events.
    original_event = build_lifecycle_events(original)[-1]
    replayed_event = build_lifecycle_events(replayed)[-1]

    # Then: immutable source identity wins over the transient retry clock.
    assert replayed_event.event_id == original_event.event_id


def test_first_daily_bar_creates_conservative_cross_schema_listing_evidence() -> None:
    # Given: an accepted first daily observation for a code absent from stock_basic.
    source = replace(
        _master_record(),
        schema_manifest_id="schema_daily",
        source_snapshot_id="snap_daily",
        source_row_sha256="d" * 64,
        event_time=datetime(2020, 1, 2, 15, 0, tzinfo=SHANGHAI),
        available_at=datetime(2020, 1, 2, 16, 0, tzinfo=SHANGHAI),
        business_fields=(("ts_code", "300114.SZ"), ("trade_date", "20200102")),
    )

    # When: the first observed trade is converted into universe evidence.
    event = build_first_trade_event(source, "schema_universe")

    # Then: input and output schemas remain distinct and no exact listing date is invented.
    assert event.event_type is SecurityEventType.FIRST_TRADED
    assert event.effective_at == source.event_time
    assert event.available_at == source.available_at
    assert event.input_schema_manifest_id == "schema_daily"
    assert event.schema_manifest_id == "schema_universe"


def _master_record() -> CanonicalRecord:
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    schema = registry.endpoint("stock_basic")
    values = (
        "000001.SZ",
        "000001",
        "平安银行",
        "深圳",
        "银行",
        "平安银行股份有限公司",
        None,
        "payh",
        "主板",
        "SZSE",
        "CNY",
        "D",
        "20200102",
        "20210105",
        "S",
        None,
        None,
    )
    return _canonical_record(registry, schema.field_names, "stock_basic", values)


def _name_record() -> CanonicalRecord:
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    schema = registry.endpoint("namechange")
    values = ("000001.SZ", "ST平安", "20200501", "20200630", "20200430", "ST")
    return _canonical_record(registry, schema.field_names, "namechange", values)


def _canonical_record(
    registry: SchemaRegistry,
    fields: tuple[str, ...],
    endpoint: str,
    values: tuple[str | None, ...],
) -> CanonicalRecord:
    schema = registry.endpoint(endpoint)
    query = TushareQuery(endpoint=endpoint, params=(), fields=fields)
    raw = build_raw_snapshot(
        query,
        TushareClient.table_for_test(fields, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(OBSERVED, OBSERVED),
    )
    return canonicalize_batch(raw, schema, registry.manifest_id).records[0]
