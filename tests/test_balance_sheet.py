from datetime import datetime
from zoneinfo import ZoneInfo

from ashare_lab.data.balance_sheets import build_balance_sheet_version
from ashare_lab.data.queries import balance_sheet_security_queries
from tests.balance_sheet_support import canonical_record, registry

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_balance_sheet_version_uses_actual_publication_clock() -> None:
    # Given: one report observed after its actual publication date.
    record = canonical_record()

    # When: it crosses the balance-sheet PIT boundary.
    event = build_balance_sheet_version(record)

    # Then: report period remains economic time and actual publication controls visibility.
    assert event.end_date == "20251231"
    assert event.available_at == datetime(2026, 3, 22, 18, 0, tzinfo=SHANGHAI)
    assert event.total_assets == 100.0
    assert event.total_liab_hldr_eqy == 180.0


def test_balance_sheet_canonical_is_quarantined_until_pit_projection() -> None:
    # Given / When: a governed provider row is canonicalized.
    record = canonical_record()

    # Then: canonical data cannot directly enter research features.
    assert record.quality_status == "QUARANTINED"


def test_balance_sheet_queries_pin_lifecycle_code_and_range() -> None:
    # Given: two historical lifecycle codes under the independent schema.
    schema_registry = registry()

    # When: bounded standard-interface requests are built.
    built = balance_sheet_security_queries(
        schema_registry,
        ("000001.SZ", "600000.SH"),
        "20200101",
        "20260716",
    )

    # Then: each request has a fixed code, announcement range, and field projection.
    assert tuple(query.endpoint for query in built) == ("balancesheet", "balancesheet")
    assert tuple(query.params[0].value for query in built) == ("000001.SZ", "600000.SH")
    assert tuple(param.value for param in built[0].params[1:]) == ("20200101", "20260716")
    assert all(
        query.fields == schema_registry.endpoint("balancesheet").field_names for query in built
    )
