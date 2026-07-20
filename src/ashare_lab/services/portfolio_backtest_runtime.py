"""Composition root for a real governed development portfolio backtest."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from ashare_lab.backtest.portfolio_contracts import PortfolioBacktestInputError
from ashare_lab.backtest.portfolio_engine import PortfolioBacktestConfig, PortfolioBacktestEngine
from ashare_lab.backtest.portfolio_metrics import (
    PortfolioMetricInputError,
    calculate_portfolio_metrics,
)
from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
    PortfolioBacktestReportStoreError,
)
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.config import DataSettings
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.portfolio.research_store import (
    PortfolioTargetDescriptor,
    PortfolioTargetStore,
    PortfolioTargetStoreError,
)
from ashare_lab.research.data_quality import DataIntegrityError, TemporalLeakageError
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.datasets.spec_store import (
    DatasetSpecDescriptor,
    DatasetSpecStore,
    DatasetSpecStoreError,
)
from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleConflictError,
    MarketBundleReaderError,
)
from ashare_lab.research.features.market.mongo_reader import MongoMarketBundleReader
from ashare_lab.research.labels.mongo_benchmark_reader import (
    BenchmarkSnapshotBoundary,
    read_dataset_benchmark_observations,
)
from ashare_lab.services.factor_calendar_runtime import (
    FactorCalendarRuntimeError,
    load_dataset_development_calendar,
)
from ashare_lab.services.market_feature_runtime import MongoDatabaseView
from ashare_lab.services.portfolio_backtest import (
    PortfolioBacktestAssemblyError,
    PortfolioBacktestRunInputs,
    build_portfolio_backtest_inputs,
)

_BENCHMARK_SYMBOL: Final = "000905.SH"


@dataclass(frozen=True, slots=True)
class BoundPortfolioBacktestInputs:
    """Engine inputs plus exact schema and Raw snapshot provenance."""

    run_inputs: PortfolioBacktestRunInputs
    source_snapshot_ids: tuple[str, ...]
    market_schema_manifest_id: str
    benchmark_schema_manifest_id: str


class PortfolioBacktestRuntimeError(Exception):
    """Frozen portfolio and market evidence cannot produce a real report."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable portfolio backtest runtime failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"portfolio_backtest_runtime: {self.detail}"


def run_default_portfolio_backtest(
    project_root: Path,
    target_artifact_id: str,
) -> PortfolioBacktestReportDescriptor:
    """Run and publish one development-only report from an exact target artifact."""
    artifact_root = project_root / "data" / "artifacts"
    try:
        target_path = artifact_root / "portfolio_targets" / target_artifact_id / "targets.json"
        targets = PortfolioTargetStore(artifact_root).read(
            PortfolioTargetDescriptor(
                artifact_id=target_artifact_id,
                artifact_path=target_path,
                data_sha256=_sha256(target_path),
            )
        )
        dataset_path = _sole_path(artifact_root / "dataset_spec", "ds_*/manifest.json")
        spec = DatasetSpecStore(artifact_root).read(
            DatasetSpecDescriptor(
                dataset_path.parent.name,
                dataset_path,
                _sha256(dataset_path),
            )
        )
        if targets.dataset_snapshot_id != spec.snapshot_id:
            detail = "portfolio target crosses DatasetSpec boundary"
            raise PortfolioBacktestRuntimeError(detail)
        bound = load_default_backtest_inputs(project_root, spec, targets)
        if {
            bound.market_schema_manifest_id,
            bound.benchmark_schema_manifest_id,
        } - set(spec.input_schema_manifest_ids):
            detail = "backtest schema is absent from DatasetSpec"
            raise PortfolioBacktestRuntimeError(detail)
        if set(bound.source_snapshot_ids) - set(spec.source_snapshot_ids):
            detail = "backtest Raw snapshot is absent from DatasetSpec"
            raise PortfolioBacktestRuntimeError(detail)
        result = PortfolioBacktestEngine(PortfolioBacktestConfig(initial_cash=1_000_000.0)).run(
            bound.run_inputs.sessions, bound.run_inputs.signals
        )
        metrics = calculate_portfolio_metrics(result, bound.run_inputs.benchmark)
        report = PortfolioBacktestReport(
            target_artifact_id=target_artifact_id,
            factor_report_id=targets.factor_report_id,
            dataset_snapshot_id=spec.snapshot_id,
            market_schema_manifest_id=bound.market_schema_manifest_id,
            benchmark_schema_manifest_id=bound.benchmark_schema_manifest_id,
            source_snapshot_ids=bound.source_snapshot_ids,
            benchmark_symbol=_BENCHMARK_SYMBOL,
            benchmark_price_basis="raw_open",
            cost_rule_version="china_a_cost_v1",
            risk_rule_version="portfolio_risk_v1",
            final_test_runs=0,
            result=result,
            metrics=metrics,
        )
        return PortfolioBacktestReportStore(artifact_root).write(report)
    except (
        OSError,
        ValidationError,
        PyMongoError,
        DatasetSpecStoreError,
        PortfolioTargetStoreError,
        PortfolioBacktestReportStoreError,
        FactorCalendarRuntimeError,
        MarketBundleConflictError,
        MarketBundleReaderError,
        PortfolioBacktestAssemblyError,
        PortfolioBacktestInputError,
        PortfolioMetricInputError,
        DataIntegrityError,
        TemporalLeakageError,
    ) as error:
        raise PortfolioBacktestRuntimeError(str(error)) from error


def load_default_backtest_inputs(
    project_root: Path,
    spec: DatasetSpec,
    targets: PortfolioTargetBatch,
) -> BoundPortfolioBacktestInputs:
    """Read only DatasetSpec-bound market and benchmark evidence from Mongo."""
    market_schema = SchemaRegistry.load(project_root / "schemas" / "tushare_p0_v1.json")
    benchmark_schema = SchemaRegistry.load(project_root / "schemas" / "tushare_benchmarks_v1.json")
    schema_ids = {market_schema.manifest_id, benchmark_schema.manifest_id}
    if schema_ids - set(spec.input_schema_manifest_ids):
        detail = "required market or benchmark schema is absent from DatasetSpec"
        raise PortfolioBacktestRuntimeError(detail)
    calendar = load_dataset_development_calendar(project_root, spec)
    start_date = targets.records[0].decision_date
    run_calendar = tuple(day for day in calendar if day >= start_date)
    if not run_calendar:
        detail = "backtest calendar is empty after the first portfolio target"
        raise PortfolioBacktestRuntimeError(detail)
    symbols = tuple(
        sorted({item.symbol for record in targets.records for item in record.positions})
    )
    settings = DataSettings()
    with MongoClient[BsonDocument](
        settings.mongodb_uri,
        serverSelectionTimeoutMS=8_000,
    ) as client:
        database = MongoDatabaseView(client[settings.mongodb_database])
        market = MongoMarketBundleReader(database).read(
            run_calendar[0],
            run_calendar[-1],
            market_schema.manifest_id,
            allowed_snapshot_ids=spec.source_snapshot_ids,
            symbols=symbols,
        )
        benchmark = read_dataset_benchmark_observations(
            database,
            run_calendar[0],
            run_calendar[-1],
            _BENCHMARK_SYMBOL,
            BenchmarkSnapshotBoundary(
                benchmark_schema.manifest_id,
                spec.source_snapshot_ids,
            ),
        )
    source_ids = {
        snapshot_id
        for observation in market.observations
        for snapshot_id in observation.source_snapshot_ids
    }
    source_ids.update(item.source_snapshot_id for item in benchmark)
    return BoundPortfolioBacktestInputs(
        build_portfolio_backtest_inputs(targets, run_calendar, market, benchmark),
        tuple(sorted(source_ids)),
        market_schema.manifest_id,
        benchmark_schema.manifest_id,
    )


def _sole_path(root: Path, pattern: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one artifact, found {len(paths)}"
        raise PortfolioBacktestRuntimeError(detail)
    return paths[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
