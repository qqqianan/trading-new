from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from ashare_lab import coverage_cli
from ashare_lab.coverage_cli import app
from ashare_lab.research.datasets.artifact_store import DatasetArtifactWriteResult
from ashare_lab.research.datasets.coverage import (
    ComponentCoverage,
    CoverageRequest,
    DatasetComponent,
    DatasetCoverageReport,
    DatasetInputManifest,
    QualificationStatus,
)
from ashare_lab.services.dataset_coverage import DatasetCoverageRun, DatasetCoverageService

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Reader:
    def __init__(self, components: tuple[ComponentCoverage, ...]) -> None:
        self._components = components

    def components(self, request: CoverageRequest) -> tuple[ComponentCoverage, ...]:
        del request
        return self._components


class _Store:
    def __init__(self) -> None:
        self.manifest_count = -1

    def write(
        self,
        report: DatasetCoverageReport,
        manifest: DatasetInputManifest | None,
        recorded_at: datetime,
    ) -> DatasetArtifactWriteResult:
        del report, recorded_at
        self.manifest_count = 1 if manifest is not None else 0
        return DatasetArtifactWriteResult(1, 1, 1, self.manifest_count)


def _component(*, quality_passed: bool = True) -> ComponentCoverage:
    return ComponentCoverage(
        component=DatasetComponent.MARKET_DAILY,
        start_date=date(2020, 1, 2),
        end_date=date(2026, 7, 16),
        schema_manifest_ids=("schema_market",),
        source_snapshot_ids=("snap_market",),
        lineage_edge_ids=("lineage_market",),
        quality_passed=quality_passed,
        point_in_time=True,
    )


def test_coverage_service_persists_manifest_only_after_unique_qualification() -> None:
    # Given: complete reader-derived evidence and an append-only artifact sink.
    store = _Store()
    service = DatasetCoverageService(_Reader((_component(),)), store)
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2026, 7, 16),
        (DatasetComponent.MARKET_DAILY,),
    )

    # When: the service invokes the sole qualification decision function.
    run = service.qualify(request, datetime(2026, 7, 17, 20, 0, tzinfo=SHANGHAI))

    # Then: a qualified report and content-addressed input manifest are persisted together.
    assert run.report.status is QualificationStatus.QUALIFIED
    assert run.manifest is not None
    assert store.manifest_count == 1


def test_coverage_service_persists_blocked_report_without_manifest() -> None:
    # Given: reader-derived evidence whose quality chain failed.
    store = _Store()
    service = DatasetCoverageService(_Reader((_component(quality_passed=False),)), store)
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2026, 7, 16),
        (DatasetComponent.MARKET_DAILY,),
    )

    # When: qualification fails closed.
    run = service.qualify(request, datetime(2026, 7, 17, 20, 0, tzinfo=SHANGHAI))

    # Then: the audit report remains durable but no training input manifest exists.
    assert run.report.status is QualificationStatus.BLOCKED
    assert run.manifest is None
    assert store.manifest_count == 0


def test_coverage_cli_exposes_dates_and_industry_requirement_without_quality_flags() -> None:
    # Given: the production coverage CLI composition boundary.
    runner = CliRunner()

    # When: an operator inspects the qualification contract.
    result = runner.invoke(app, ["--help"])

    # Then: evidence decisions are not caller-declared CLI inputs.
    assert result.exit_code == 0
    assert "start-date" in result.stdout
    assert "require-industry" in result.stdout
    assert "quality-passed" not in result.stdout
    assert "point-in-time" not in result.stdout


@pytest.mark.parametrize(("quality_passed", "exit_code"), [(True, 0), (False, 2)])
def test_coverage_cli_reports_derived_status_and_returns_nonzero_when_blocked(
    monkeypatch: pytest.MonkeyPatch,
    *,
    quality_passed: bool,
    exit_code: int,
) -> None:
    # Given: a service result derived from either complete or failed quality evidence.
    service = DatasetCoverageService(
        _Reader((_component(quality_passed=quality_passed),)),
        _Store(),
    )
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2026, 7, 16),
        (DatasetComponent.MARKET_DAILY,),
    )
    run = service.qualify(request, datetime(2026, 7, 18, 9, 0, tzinfo=SHANGHAI))

    def replacement(
        start_date: date,
        end_date: date,
        *,
        require_industry: bool,
    ) -> DatasetCoverageRun:
        del start_date, end_date, require_industry
        return run

    monkeypatch.setattr(
        coverage_cli,
        "qualify_default_dataset",
        replacement,
    )

    # When: the operator invokes qualification without caller-declared evidence flags.
    result = CliRunner().invoke(
        app,
        [
            "--start-date",
            "2020-01-02",
            "--end-date",
            "2026-07-16",
        ],
    )

    # Then: blocked evidence is observable through both output and process status.
    assert result.exit_code == exit_code
    assert f"status={run.report.status.value}" in result.stdout
