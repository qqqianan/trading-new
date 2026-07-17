from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.mongo_schema import MongoSchemaBuilder
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.research.datasets.artifact_store import (
    MongoDatasetArtifactStore,
    coverage_report_document,
    input_manifest_document,
)
from ashare_lab.research.datasets.coverage import (
    ComponentCoverage,
    CoverageRequest,
    DatasetComponent,
    DatasetCoverageError,
    QualificationStatus,
    build_input_manifest,
    qualify_dataset,
)
from ashare_lab.research.datasets.identity_chunks import IdentityKind, build_identity_chunks
from tests.test_balance_sheet_store import Database

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _component(
    name: DatasetComponent,
    start: date = date(2020, 1, 2),
    end: date = date(2026, 7, 14),
) -> ComponentCoverage:
    suffix = name.value.replace("_", "")
    return ComponentCoverage(
        component=name,
        start_date=start,
        end_date=end,
        schema_manifest_ids=(f"schema_{suffix}",),
        source_snapshot_ids=(f"snap_{suffix}",),
        lineage_edge_ids=(f"lineage_{suffix}",),
        quality_passed=True,
        point_in_time=True,
    )


def test_coverage_report_qualifies_only_common_required_interval() -> None:
    # Given: market, universe, and benchmark evidence covering one requested range.
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2026, 6, 16),
        (
            DatasetComponent.MARKET_DAILY,
            DatasetComponent.UNIVERSE,
            DatasetComponent.BENCHMARK_DAILY,
        ),
    )
    components = tuple(_component(component) for component in request.required_components)

    # When: cross-table qualification and input manifest construction run.
    report = qualify_dataset(request, components)
    manifest = build_input_manifest(report)

    # Then: the decision and every immutable evidence identity are pinned.
    assert report.status is QualificationStatus.QUALIFIED
    assert report.qualified_start == date(2020, 1, 2)
    assert report.qualified_end == date(2026, 7, 14)
    assert manifest.coverage_report_id == report.report_id
    assert len(manifest.input_schema_manifest_ids) == 3
    assert manifest.schema_manifest_id.startswith("schema_")
    assert manifest.lineage_manifest_id.startswith("lineage_")


def test_industry_requirement_blocks_dates_before_first_observation() -> None:
    # Given: industry membership known only from the current observation onward.
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2026, 6, 16),
        (DatasetComponent.MARKET_DAILY, DatasetComponent.INDUSTRY),
    )
    components = (
        _component(DatasetComponent.MARKET_DAILY),
        _component(
            DatasetComponent.INDUSTRY,
            start=date(2026, 7, 17),
            end=date(2026, 7, 17),
        ),
    )

    # When: the historical range is qualified.
    report = qualify_dataset(request, components)

    # Then: effective intervals cannot masquerade as historical availability.
    assert report.status is QualificationStatus.BLOCKED
    assert "industry_pit:starts_after_request" in report.blockers
    with pytest.raises(DatasetCoverageError, match="not qualified"):
        build_input_manifest(report)


def test_missing_lineage_blocks_manifest_even_when_dates_overlap() -> None:
    # Given: a component with dates and quality but no Raw-to-output lineage.
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2021, 1, 1),
        (DatasetComponent.MARKET_DAILY,),
    )
    market = _component(DatasetComponent.MARKET_DAILY)
    incomplete = ComponentCoverage(
        component=market.component,
        start_date=market.start_date,
        end_date=market.end_date,
        schema_manifest_ids=market.schema_manifest_ids,
        source_snapshot_ids=market.source_snapshot_ids,
        lineage_edge_ids=(),
        quality_passed=True,
        point_in_time=True,
    )

    # When: evidence completeness is evaluated.
    report = qualify_dataset(request, (incomplete,))

    # Then: date overlap alone never authorizes a dataset.
    assert report.status is QualificationStatus.BLOCKED
    assert "market_daily_bundle:missing_lineage" in report.blockers


@pytest.mark.parametrize(
    "coverage_request",
    [
        CoverageRequest(
            date(2021, 1, 2),
            date(2021, 1, 1),
            (DatasetComponent.MARKET_DAILY,),
        ),
        CoverageRequest(date(2021, 1, 1), date(2021, 1, 2), ()),
    ],
)
def test_invalid_coverage_requests_fail_before_evidence_use(
    coverage_request: CoverageRequest,
) -> None:
    # Given: an impossible interval or an empty component contract.
    # When / Then: malformed requests cannot produce qualification artifacts.
    with pytest.raises(DatasetCoverageError, match="coverage request"):
        qualify_dataset(coverage_request, ())


def test_duplicate_component_evidence_is_rejected() -> None:
    # Given: two conflicting rows for the same governed component.
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2021, 1, 1),
        (DatasetComponent.MARKET_DAILY,),
    )
    market = _component(DatasetComponent.MARKET_DAILY)

    # When / Then: ambiguity is rejected instead of choosing one row.
    with pytest.raises(DatasetCoverageError, match="duplicate components"):
        qualify_dataset(request, (market, market))


def test_component_matrix_reports_all_evidence_failures() -> None:
    # Given: one required component with no dates, schema, Raw, quality, or PIT proof.
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2021, 1, 1),
        (DatasetComponent.UNIVERSE, DatasetComponent.BENCHMARK_DAILY),
    )
    universe = ComponentCoverage(
        component=DatasetComponent.UNIVERSE,
        start_date=None,
        end_date=None,
        schema_manifest_ids=(),
        source_snapshot_ids=(),
        lineage_edge_ids=(),
        quality_passed=False,
        point_in_time=False,
        blockers=("provider_incomplete",),
    )

    # When: the full matrix is evaluated.
    report = qualify_dataset(request, (universe,))

    # Then: no missing proof is hidden behind the first failure.
    assert report.status is QualificationStatus.BLOCKED
    assert "benchmark_daily:missing_component" in report.blockers
    assert "universe_pit:missing_date_coverage" in report.blockers
    assert "universe_pit:missing_schema" in report.blockers
    assert "universe_pit:missing_raw_snapshots" in report.blockers
    assert "universe_pit:quality_failed" in report.blockers
    assert "universe_pit:not_point_in_time" in report.blockers


def test_dataset_artifact_schema_closes_report_component_and_manifest_collections() -> None:
    # Given: the committed schema for derived dataset governance artifacts.
    registry = SchemaRegistry.load(ROOT / "schemas" / "research_dataset_v1.json")

    # When: Mongo validators are generated.
    plan = MongoSchemaBuilder(registry).collection_plan()

    # Then: reports, matrices, manifests, and bounded identity chunks are registered.
    assert registry.schema_version == "1.1.0"
    assert registry.endpoint_names == ()
    assert set(plan) == {
        "dataset_component_coverage",
        "dataset_coverage_reports",
        "dataset_identity_chunks",
        "dataset_input_manifests",
    }


def test_identity_chunks_are_bounded_content_addressed_and_complete() -> None:
    # Given: more immutable lineage IDs than one bounded Mongo chunk may contain.
    identities = tuple(f"lineage_{index:04d}" for index in range(2_001))

    # When: the identity manifest is split for append-only persistence.
    chunks = build_identity_chunks("manifest_001", IdentityKind.LINEAGE_EDGE, identities)

    # Then: every identity appears once and repeated construction is stable.
    assert tuple(identity for chunk in chunks for identity in chunk.identity_ids) == identities
    assert tuple(len(chunk.identity_ids) for chunk in chunks) == (1_000, 1_000, 1)
    assert chunks == build_identity_chunks("manifest_001", IdentityKind.LINEAGE_EDGE, identities)


def test_dataset_artifact_store_appends_report_matrix_and_manifest() -> None:
    # Given: a qualified report, its input manifest, and an isolated Mongo fake.
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2021, 1, 1),
        (DatasetComponent.MARKET_DAILY,),
    )
    report = qualify_dataset(request, (_component(DatasetComponent.MARKET_DAILY),))
    manifest = build_input_manifest(report)
    database = Database()
    store = MongoDatasetArtifactStore.__new__(MongoDatasetArtifactStore)
    store.__dict__["_database"] = database
    recorded_at = datetime(2026, 7, 17, 19, 0, tzinfo=SHANGHAI)

    # When: the complete qualification artifact crosses the persistence boundary.
    result = store.write(report, manifest, recorded_at)

    # Then: every immutable level is written once under its content identity.
    assert coverage_report_document(report, recorded_at)["status"] == "QUALIFIED"
    assert input_manifest_document(manifest, recorded_at)["manifest_id"] == manifest.manifest_id
    assert result.component_count == 1
    assert database["dataset_coverage_reports"].update_calls == 1
    assert database["dataset_component_coverage"].bulk_calls == 1
    assert database["dataset_identity_chunks"].bulk_calls == 1
    assert database["dataset_input_manifests"].update_calls == 1
