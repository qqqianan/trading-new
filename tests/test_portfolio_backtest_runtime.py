from datetime import date
from pathlib import Path
from types import GenericAlias, TracebackType
from typing import Self

import pytest

from ashare_lab.backtest.portfolio_contracts import PortfolioSession, PortfolioSignal
from ashare_lab.backtest.portfolio_metrics import BenchmarkPoint
from ashare_lab.backtest.report_store import PortfolioBacktestReportStore
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.domain.market import Symbol
from ashare_lab.portfolio import PortfolioTarget, TargetPosition
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.portfolio.research_store import PortfolioTargetStore
from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.datasets.spec_store import DatasetSpecStore
from ashare_lab.research.features.market.mongo_contracts import MarketBundleReadResult
from ashare_lab.research.labels.models import BenchmarkOpenObservation
from ashare_lab.research.labels.mongo_benchmark_reader import BenchmarkSnapshotBoundary
from ashare_lab.services import portfolio_backtest_runtime
from ashare_lab.services.portfolio_backtest import PortfolioBacktestRunInputs
from ashare_lab.services.portfolio_backtest_runtime import (
    BoundPortfolioBacktestInputs,
    PortfolioBacktestRuntimeError,
    load_default_backtest_inputs,
    run_default_portfolio_backtest,
)

from .portfolio_backtest_support import bar, market, trading_date
from .test_portfolio_backtest_inputs import benchmark_observation, market_observation
from .test_portfolio_composition import portfolio_spec
from .test_portfolio_runtime import single_factor_batch

ROOT = Path(__file__).parents[1]


def test_backtest_runtime_reports_missing_target_artifact(tmp_path: Path) -> None:
    # Given / When / Then: an absent explicit identity fails at the runtime boundary.
    with pytest.raises(PortfolioBacktestRuntimeError, match="portfolio_backtest_runtime"):
        run_default_portfolio_backtest(tmp_path, "portfolio_targets_" + "a" * 64)


def test_real_backtest_runtime_binds_targets_dataset_risk_and_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: real immutable target/DatasetSpec stores and label-free market inputs.
    artifact_root = tmp_path / "data" / "artifacts"
    spec = portfolio_spec()
    DatasetSpecStore(artifact_root).write(spec)
    initial = single_factor_batch()
    record = initial.records[0].model_copy(update={"decision_date": trading_date(0)})
    batch = initial.model_copy(
        update={"dataset_snapshot_id": spec.snapshot_id, "records": (record,)}
    )
    target_descriptor = PortfolioTargetStore(artifact_root).write(batch)
    decision = trading_date(0)
    next_day = trading_date(1)
    symbols = tuple(item.symbol for item in batch.records[0].positions)
    sessions = (
        PortfolioSession(decision, tuple(bar(symbol, 0, 10.0) for symbol in symbols)),
        PortfolioSession(next_day, tuple(bar(symbol, 1, 10.0) for symbol in symbols)),
    )
    signal = PortfolioSignal(
        target=PortfolioTarget(
            decision,
            batch.factor_report_id,
            tuple(
                TargetPosition(Symbol(item.symbol), item.target_weight, item.score)
                for item in record.positions
            ),
            record.cash_weight,
        ),
        market=market(symbols, industry=None),
    )
    inputs = BoundPortfolioBacktestInputs(
        run_inputs=PortfolioBacktestRunInputs(
            sessions,
            (signal,),
            (BenchmarkPoint(decision, 5_000.0), BenchmarkPoint(next_day, 5_010.0)),
        ),
        source_snapshot_ids=spec.source_snapshot_ids,
        market_schema_manifest_id=spec.input_schema_manifest_ids[0],
        benchmark_schema_manifest_id=spec.input_schema_manifest_ids[0],
    )

    def load_inputs(
        _root: Path,
        _specification: DatasetSpec,
        _batch: PortfolioTargetBatch,
    ) -> BoundPortfolioBacktestInputs:
        return inputs

    monkeypatch.setattr(portfolio_backtest_runtime, "load_default_backtest_inputs", load_inputs)

    # When: the real composition root runs and publishes the development report.
    descriptor = run_default_portfolio_backtest(tmp_path, target_descriptor.artifact_id)

    # Then: the report is bound to exact inputs, remains DRAFT, and keeps holdout sealed.
    report = PortfolioBacktestReportStore(artifact_root).read(descriptor)
    assert report.target_artifact_id == target_descriptor.artifact_id
    assert report.dataset_snapshot_id == spec.snapshot_id
    assert report.result.research_status.value == "DRAFT"
    assert report.final_test_runs == 0


class MemoryDatabase:
    """Named database boundary whose collections are owned by patched readers."""

    name = "ashare_quant"


class MemoryClient:
    """Context-managed client used to prove runtime connection ownership."""

    def __init__(self, _uri: str, *, serverSelectionTimeoutMS: int) -> None:  # noqa: N803
        assert serverSelectionTimeoutMS == 8_000

    @classmethod
    def __class_getitem__(cls, _item: GenericAlias) -> type[Self]:
        return cls

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def __getitem__(self, _name: str) -> MemoryDatabase:
        return MemoryDatabase()


def test_default_backtest_input_adapter_binds_queries_and_exact_source_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: real schema identities with in-memory DatasetSpec-bound market evidence.
    initial = single_factor_batch()
    record = initial.records[0].model_copy(update={"decision_date": trading_date(0)})
    targets = initial.model_copy(update={"records": (record,)})
    symbols = tuple(item.symbol for item in record.positions)
    observations = tuple(
        market_observation(symbol, day, 10.0)
        for day in (trading_date(0), trading_date(1))
        for symbol in symbols
    )
    benchmarks = (
        benchmark_observation(trading_date(0), 5_000.0),
        benchmark_observation(trading_date(1), 5_010.0),
    )
    source_ids = tuple(
        sorted(
            {
                *(snapshot for item in observations for snapshot in item.source_snapshot_ids),
                *(item.source_snapshot_id for item in benchmarks),
            }
        )
    )
    market_schema = SchemaRegistry.load(ROOT / "schemas" / "tushare_p0_v1.json")
    benchmark_schema = SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")
    base_spec = portfolio_spec()
    spec = base_spec.model_copy(
        update={
            "input_schema_manifest_ids": (
                market_schema.manifest_id,
                benchmark_schema.manifest_id,
            ),
            "source_snapshot_ids": source_ids,
        }
    )
    market_result = MarketBundleReadResult(observations, (), ())
    market_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    class MemoryReader:
        def __init__(self, _database: MemoryDatabase) -> None:
            pass

        def read(
            self,
            _start: date,
            _end: date,
            _schema: str,
            *,
            allowed_snapshot_ids: tuple[str, ...] | None = None,
            symbols: tuple[str, ...] | None = None,
        ) -> MarketBundleReadResult:
            assert allowed_snapshot_ids is not None
            assert symbols is not None
            market_calls.append((allowed_snapshot_ids, symbols))
            return market_result

    def benchmark_reader(
        _database: MemoryDatabase,
        _start: date,
        _end: date,
        _symbol: str,
        _boundary: BenchmarkSnapshotBoundary,
    ) -> tuple[BenchmarkOpenObservation, ...]:
        return benchmarks

    def database_view(_database: MemoryDatabase) -> MemoryDatabase:
        return MemoryDatabase()

    def calendar_loader(_root: Path, _spec: DatasetSpec) -> tuple[date, ...]:
        return (trading_date(0), trading_date(1))

    monkeypatch.setattr(portfolio_backtest_runtime, "MongoClient", MemoryClient)
    monkeypatch.setattr(portfolio_backtest_runtime, "MongoDatabaseView", database_view)
    monkeypatch.setattr(portfolio_backtest_runtime, "MongoMarketBundleReader", MemoryReader)
    monkeypatch.setattr(
        portfolio_backtest_runtime,
        "read_dataset_benchmark_observations",
        benchmark_reader,
    )
    monkeypatch.setattr(
        portfolio_backtest_runtime,
        "load_dataset_development_calendar",
        calendar_loader,
    )

    # When: the real default adapter assembles its Mongo query and engine inputs.
    result = load_default_backtest_inputs(ROOT, spec, targets)

    # Then: DatasetSpec allowlists reach the reader and exact used snapshots are retained.
    assert market_calls == [(spec.source_snapshot_ids, tuple(sorted(symbols)))]
    assert result.run_inputs.sessions[0].bars[0].volume == 100_000
    assert result.source_snapshot_ids == source_ids
