from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data import corporate_actions
from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.schema_registry import SchemaContractError

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_dividend_row_splits_plan_from_later_implementation_fields() -> None:
    # Given: a governed row containing both proposal and implementation facts.
    record = _record()

    # When: it is projected into lifecycle-safe PIT events.
    events = corporate_actions.build_dividend_events(record)

    # Then: proposal visibility cannot expose later execution dates.
    assert tuple(event.event_type.value for event in events) == (
        "PLAN_ANNOUNCED",
        "IMPLEMENTATION_ANNOUNCED",
    )
    assert events[0].effective_at == datetime(2026, 3, 20, 18, 0, tzinfo=SHANGHAI)
    assert events[0].record_date is None
    assert events[0].ex_date is None
    assert events[0].pay_date is None
    assert events[1].effective_at == datetime(2026, 5, 25, 18, 0, tzinfo=SHANGHAI)
    assert events[1].record_date == "20260601"
    assert events[1].ex_date == "20260602"


def test_dividend_visibility_requires_effective_and_available_clocks() -> None:
    # Given: plan and implementation events from one immutable source row.
    events = corporate_actions.build_dividend_events(_record())

    # When: queried after the plan but before implementation announcement.
    visible = corporate_actions.select_dividend_events(
        events,
        datetime(2026, 4, 1, 9, 0, tzinfo=SHANGHAI),
    )

    # Then: only the plan is visible and naive decision clocks fail closed.
    assert tuple(event.event_type.value for event in visible) == ("PLAN_ANNOUNCED",)
    with pytest.raises(ValueError, match="timezone-aware"):
        corporate_actions.select_dividend_events(
            events,
            datetime(2026, 4, 1),  # noqa: DTZ001 - exercises the rejection boundary.
        )


def test_reobserved_dividend_row_keeps_stable_event_identities() -> None:
    # Given: identical content evidence replayed with later system clocks.
    first = _record()
    replayed = CanonicalRecord(
        record_id=first.record_id,
        schema_manifest_id=first.schema_manifest_id,
        source_snapshot_id=first.source_snapshot_id,
        source_row_sha256=first.source_row_sha256,
        transform_name=first.transform_name,
        transform_version=first.transform_version,
        event_time=first.event_time,
        available_at=datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI),
        ingested_at=datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI),
        quality_status=first.quality_status,
        quality_report_id=first.quality_report_id,
        business_fields=first.business_fields,
    )

    # When: both observations are projected.
    original_ids = tuple(event.event_id for event in corporate_actions.build_dividend_events(first))
    replayed_ids = tuple(
        event.event_id for event in corporate_actions.build_dividend_events(replayed)
    )

    # Then: retry clocks cannot manufacture new corporate-action facts.
    assert replayed_ids == original_ids


def test_dividend_builder_rejects_invalid_announcement_field_type() -> None:
    # Given: a provider row whose announcement date violates the committed string type.
    record = _record()
    invalid = replace(
        record,
        business_fields=tuple(
            (name, 20260320 if name == "ann_date" else value)
            for name, value in record.business_fields
        ),
    )

    # When / Then: the PIT boundary rejects the malformed stage clock.
    with pytest.raises(SchemaContractError, match="ann_date"):
        corporate_actions.build_dividend_events(invalid)


def _record() -> CanonicalRecord:
    observed = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)
    return CanonicalRecord(
        record_id="record_dividend",
        schema_manifest_id="schema_dividend",
        source_snapshot_id="snap_dividend",
        source_row_sha256="a" * 64,
        transform_name="tushare_raw_to_canonical",
        transform_version="1.1.2",
        event_time=datetime(2025, 12, 31, 0, 0, tzinfo=SHANGHAI),
        available_at=datetime(2026, 3, 20, 18, 0, tzinfo=SHANGHAI),
        ingested_at=observed,
        quality_status="QUARANTINED",
        quality_report_id="quality_dividend",
        business_fields=(
            ("ts_code", "000001.SZ"),
            ("end_date", "20251231"),
            ("ann_date", "20260320"),
            ("div_proc", "实施"),
            ("stk_div", 0.0),
            ("stk_bo_rate", 0.0),
            ("stk_co_rate", 0.0),
            ("cash_div", 0.5),
            ("cash_div_tax", 0.45),
            ("record_date", "20260601"),
            ("ex_date", "20260602"),
            ("pay_date", "20260602"),
            ("div_listdate", None),
            ("imp_ann_date", "20260525"),
            ("base_date", "20251231"),
            ("base_share", 100000.0),
        ),
    )
