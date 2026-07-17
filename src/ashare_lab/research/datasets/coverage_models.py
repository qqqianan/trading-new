"""Immutable models for cross-table dataset coverage evidence."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique


@unique
class DatasetComponent(StrEnum):
    """Closed governed sources that may participate in a research dataset."""

    MARKET_DAILY = "market_daily_bundle"
    UNIVERSE = "universe_pit"
    BENCHMARK_DAILY = "benchmark_daily"
    BENCHMARK_WEIGHTS = "benchmark_weights_pit"
    FINANCIALS = "financials_pit"
    INDUSTRY = "industry_pit"


@unique
class QualificationStatus(StrEnum):
    """Whether a requested dataset interval has complete governed inputs."""

    QUALIFIED = "QUALIFIED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ComponentCoverage:
    """One component's date bounds and immutable governance evidence."""

    component: DatasetComponent
    start_date: date | None
    end_date: date | None
    schema_manifest_ids: tuple[str, ...]
    source_snapshot_ids: tuple[str, ...]
    lineage_edge_ids: tuple[str, ...]
    quality_passed: bool
    point_in_time: bool
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageRequest:
    """Requested interval and exact components needed by a dataset design."""

    start_date: date
    end_date: date
    required_components: tuple[DatasetComponent, ...]


@dataclass(frozen=True, slots=True)
class DatasetCoverageReport:
    """Content-addressed qualification decision and component matrix."""

    report_id: str
    request: CoverageRequest
    status: QualificationStatus
    qualified_start: date | None
    qualified_end: date | None
    components: tuple[ComponentCoverage, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetInputManifest:
    """Immutable source, schema, and lineage identities for one qualified range."""

    manifest_id: str
    coverage_report_id: str
    schema_manifest_id: str
    lineage_manifest_id: str
    input_schema_manifest_ids: tuple[str, ...]
    source_snapshot_ids: tuple[str, ...]
    lineage_edge_ids: tuple[str, ...]


class DatasetCoverageError(Exception):
    """Coverage evidence cannot authorize a dataset input manifest."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a qualification failure with a stable explanation."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the concrete failed coverage contract."""
        return self.detail
