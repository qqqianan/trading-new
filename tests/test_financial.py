from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.canonical import CanonicalRecord
from ashare_lab.data.financials import build_income_version, select_income_versions
from ashare_lab.data.schema_registry import SchemaContractError

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_income_version_uses_publication_not_report_period_clock() -> None:
    # Given: one quarantined income row observed after its actual publication.
    record = _record()

    # When: it is projected into an immutable financial version event.
    event = build_income_version(record, "income_vip")

    # Then: the version becomes effective at publication and preserves report identity.
    assert event.effective_at == datetime(2026, 3, 22, 18, 0, tzinfo=SHANGHAI)
    assert event.end_date == "20251231"
    assert event.update_flag == "1"
    assert event.n_income_attr_p == 14.0


def test_income_version_remains_invisible_before_actual_publication() -> None:
    # Given: one accepted PIT income version.
    event = build_income_version(_record(), "income_vip")

    # When: queried one minute before its actual publication clock.
    visible = select_income_versions(
        (event,),
        datetime(2026, 3, 22, 17, 59, tzinfo=SHANGHAI),
    )

    # Then: the financial values cannot enter features early.
    assert visible == ()


def test_reobserved_income_row_keeps_one_version_identity() -> None:
    # Given: the same content evidence replayed under a later ingestion clock.
    first = _record()
    replayed = replace(
        first,
        ingested_at=datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI),
    )

    # When: both observations are eventized.
    first_event = build_income_version(first, "income_vip")
    replayed_event = build_income_version(replayed, "income_vip")

    # Then: retries cannot manufacture a new report version.
    assert replayed_event.event_id == first_event.event_id


def test_income_version_rejects_unknown_source_and_naive_clock() -> None:
    # Given: one valid canonical record and its accepted event.
    record = _record()
    event = build_income_version(record, "income")

    # When / Then: source and decision-time trust boundaries fail closed.
    with pytest.raises(SchemaContractError, match="unsupported income"):
        build_income_version(record, "unknown")
    with pytest.raises(ValueError, match="timezone-aware"):
        select_income_versions((event,), datetime(2026, 3, 23))  # noqa: DTZ001


@pytest.mark.parametrize(
    ("field", "value"),
    [("ann_date", 20260320), ("basic_eps", "invalid")],
)
def test_income_version_rejects_malformed_optional_values(field: str, value: str | int) -> None:
    # Given: a provider value that violates one committed optional field type.
    record = _record()
    invalid = replace(
        record,
        business_fields=tuple(
            (name, value if name == field else current) for name, current in record.business_fields
        ),
    )

    # When / Then: malformed values cannot cross the PIT event boundary.
    with pytest.raises(SchemaContractError, match=field):
        build_income_version(invalid, "income")


def _record() -> CanonicalRecord:
    return CanonicalRecord(
        record_id="record_income",
        schema_manifest_id="schema_financial",
        source_snapshot_id="snap_income",
        source_row_sha256="a" * 64,
        transform_name="tushare_raw_to_canonical",
        transform_version="1.1.2",
        event_time=datetime(2025, 12, 31, 0, 0, tzinfo=SHANGHAI),
        available_at=datetime(2026, 3, 22, 18, 0, tzinfo=SHANGHAI),
        ingested_at=datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI),
        quality_status="QUARANTINED",
        quality_report_id="quality_income",
        business_fields=(
            ("ts_code", "000001.SZ"),
            ("ann_date", "20260320"),
            ("f_ann_date", "20260322"),
            ("end_date", "20251231"),
            ("report_type", "1"),
            ("comp_type", "1"),
            ("end_type", "4"),
            ("basic_eps", 1.0),
            ("diluted_eps", 1.0),
            ("total_revenue", 100.0),
            ("revenue", 90.0),
            ("operate_profit", 20.0),
            ("total_profit", 18.0),
            ("income_tax", 3.0),
            ("n_income", 15.0),
            ("n_income_attr_p", 14.0),
            ("ebit", 22.0),
            ("ebitda", 25.0),
            ("rd_exp", 5.0),
            ("update_flag", "1"),
        ),
    )
