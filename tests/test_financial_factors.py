from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.research.features.financial import (
    FinancialIndicatorObservation,
    FinancialVersionConflictError,
    calculate_financial_factors,
    financial_factor_catalog,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_financial_factor_catalog_registers_fixed_six_features() -> None:
    # Given / When: the governed financial catalog is loaded.
    catalog = financial_factor_catalog()

    # Then: quality and growth fields form one closed versioned family.
    assert tuple(item.name for item in catalog) == (
        "roe",
        "grossprofit_margin",
        "ocf_to_debt",
        "debt_to_assets",
        "q_sales_yoy",
        "q_netprofit_yoy",
    )


def test_financial_factors_follow_announcement_and_revision_clocks() -> None:
    # Given: an original report, its later revision, and a newer report.
    original = financial_observation(
        "original", "20250331", datetime(2025, 4, 30, 10, tzinfo=SHANGHAI), 8.0
    )
    revision = financial_observation(
        "revision",
        "20250331",
        datetime(2025, 5, 10, 10, tzinfo=SHANGHAI),
        9.0,
        update_flag="1",
    )
    newer = financial_observation(
        "newer", "20250630", datetime(2025, 8, 30, 10, tzinfo=SHANGHAI), 10.0
    )
    versions = (newer, revision, original)

    # When: four decision clocks cross the publication boundaries.
    before = calculate_financial_factors(
        versions,
        "000001.SZ",
        original.available_at - timedelta(seconds=1),
    )
    first = calculate_financial_factors(versions, "000001.SZ", original.available_at)
    revised = calculate_financial_factors(versions, "000001.SZ", revision.available_at)
    latest = calculate_financial_factors(versions, "000001.SZ", newer.available_at)

    # Then: no version appears early and every later revision is traceable.
    assert before[0].value is None
    assert before[0].null_reason == "NO_PUBLISHED_FINANCIAL"
    assert first[0].value == 8.0
    assert first[0].source_event_id == "event_original"
    assert revised[0].value == 9.0
    assert revised[0].source_event_id == "event_revision"
    assert latest[0].value == 10.0
    assert latest[0].source_report_period == "20250630"


def test_financial_factor_selector_rejects_conflicting_same_clock_versions() -> None:
    # Given: two accepted events claim the same version key with different metrics.
    available = datetime(2025, 4, 30, 10, tzinfo=SHANGHAI)
    first = financial_observation("first", "20250331", available, 8.0)
    conflict = financial_observation("conflict", "20250331", available, 9.0)

    # When / Then: event-id ordering cannot choose an arbitrary financial truth.
    with pytest.raises(FinancialVersionConflictError, match="financial_version_conflict"):
        calculate_financial_factors((first, conflict), "000001.SZ", available)


def financial_observation(
    identity: str,
    report_period: str,
    available_at: datetime,
    roe: float,
    *,
    update_flag: str = "0",
) -> FinancialIndicatorObservation:
    return FinancialIndicatorObservation(
        event_id=f"event_{identity}",
        symbol="000001.SZ",
        available_at=available_at,
        report_period=report_period,
        update_flag=update_flag,
        roe=roe,
        grossprofit_margin=30.0,
        ocf_to_debt=0.2,
        debt_to_assets=50.0,
        q_sales_yoy=12.0,
        q_netprofit_yoy=15.0,
        source_snapshot_id=f"snapshot_{identity}",
        source_row_sha256="a" * 64,
    )
