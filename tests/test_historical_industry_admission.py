import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.capco_membership import (
    audit_capco_membership,
    build_capco_membership_candidate,
)
from ashare_lab.data.capco_membership_models import CapcoMembershipAudit
from ashare_lab.data.historical_industry_admission import (
    HistoricalIndustryAdmissionError,
    admit_capco_membership,
)
from ashare_lab.data.historical_industry_artifacts import (
    write_historical_industry_admission,
)
from ashare_lab.data.historical_industry_calendar import (
    HistoricalIndustryCalendarEvidence,
    HistoricalIndustryCalendarRow,
    build_historical_industry_calendar,
)
from ashare_lab.data.schema_registry import SchemaRegistry
from tests.test_capco_membership import LAYOUT_PAGE, Provider, _archive, _conflict

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_historical_industry_schema_is_physically_isolated_from_tushare() -> None:
    # Given: the committed official historical-industry source schema.
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v1.json")

    # When: the CAPCO admission boundary is resolved.
    endpoint = registry.endpoint("capco_membership")

    # Then: source-only Raw and canonical candidate collections are independent.
    assert registry.schema_version == "1.0.0"
    assert endpoint.raw_collection == "raw_official_capco_membership"
    assert endpoint.available_at_policy == "publication_date_next_open"


def test_capco_admission_projects_date_only_publication_to_next_open() -> None:
    # Given: exact CAPCO evidence and the governed sessions around Lunar New Year.
    report = _report()
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v1.json")
    calendar = _calendar()

    # When: the source-only admission gate evaluates Raw, quality, lineage, and time.
    admission = admit_capco_membership(
        report,
        registry,
        calendar=calendar,
        admitted_at=datetime(2026, 7, 27, 18, tzinfo=UTC),
    )

    # Then: no 2024-02-08 same-day knowledge or 2022 listing-date backfill is created.
    assert admission.raw.parent_source_audit_id == report.audit_id
    assert admission.quality.status == "QUALIFIED_SOURCE_ONLY"
    assert admission.lineage.schema_manifest_id == registry.manifest_id
    assert admission.pit_candidate.unknown_from == date(2022, 12, 28)
    assert admission.pit_candidate.available_at == datetime(2024, 2, 19, 9, 30, tzinfo=SHANGHAI)
    assert admission.pit_candidate.industry_code == "C39"
    assert admission.lineage.field_mappings[-1] == (
        f"pit_candidate.available_at<-{calendar.calendar_artifact_id}.rows.next_open_date"
    )
    assert admission.research_use_authorized is False


def test_capco_admission_rejects_calendar_for_different_publication_date() -> None:
    # Given: a governed calendar whose start does not match provider publication.
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v1.json")
    calendar = build_historical_industry_calendar(
        (
            HistoricalIndustryCalendarRow(
                cal_date="20240209",
                exchange="SSE",
                is_open=0,
                quality_status="ACCEPTED",
                schema_manifest_id=f"schema_{'a' * 64}",
                source_snapshot_id=f"snap_{'b' * 64}",
                source_row_sha256="c" * 64,
            ),
            HistoricalIndustryCalendarRow(
                cal_date="20240210",
                exchange="SSE",
                is_open=1,
                quality_status="ACCEPTED",
                schema_manifest_id=f"schema_{'a' * 64}",
                source_snapshot_id=f"snap_{'d' * 64}",
                source_row_sha256="e" * 64,
            ),
        ),
        publication_date=date(2024, 2, 9),
    )

    # When / Then: a nearby but different calendar cannot be substituted.
    with pytest.raises(HistoricalIndustryAdmissionError, match="publication"):
        admit_capco_membership(
            _report(),
            registry,
            calendar=calendar,
            admitted_at=datetime(2026, 7, 27, 18, tzinfo=UTC),
        )


def test_capco_admission_artifact_is_content_addressed(tmp_path: Path) -> None:
    # Given: one fully qualified source-only admission.
    registry = SchemaRegistry.load(ROOT / "schemas" / "historical_industry_source_v1.json")
    admission = admit_capco_membership(
        _report(),
        registry,
        calendar=_calendar(),
        admitted_at=datetime(2026, 7, 27, 18, tzinfo=UTC),
    )

    # When: identical evidence is published twice.
    first = write_historical_industry_admission(admission, tmp_path)
    second = write_historical_industry_admission(admission, tmp_path)

    # Then: immutable bytes resolve to one admission identity.
    assert first == second
    assert first.path == tmp_path / admission.admission_id / "manifest.json"


def _report() -> CapcoMembershipAudit:
    content = b"%PDF-capco"
    candidate = build_capco_membership_candidate(
        _archive(attachment_hash=hashlib.sha256(content).hexdigest()),
        _conflict(),
        year=2023,
        half=1,
    )
    return audit_capco_membership(
        Provider(content),
        candidate,
        audited_at=datetime(2026, 7, 27, 16, tzinfo=UTC),
        page_extractor=lambda _content: (LAYOUT_PAGE,),
    )


def _calendar() -> HistoricalIndustryCalendarEvidence:
    start = date(2024, 2, 8)
    rows = tuple(
        HistoricalIndustryCalendarRow(
            cal_date=(start + timedelta(days=offset)).strftime("%Y%m%d"),
            exchange="SSE",
            is_open=1 if offset in {0, 11} else 0,
            quality_status="ACCEPTED",
            schema_manifest_id=f"schema_{'a' * 64}",
            source_snapshot_id=f"snap_{offset:064x}",
            source_row_sha256=f"{offset:064x}",
        )
        for offset in range(12)
    )
    return build_historical_industry_calendar(rows, publication_date=start)
