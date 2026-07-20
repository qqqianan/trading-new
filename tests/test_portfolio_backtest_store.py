import json
from pathlib import Path

import pytest

from ashare_lab.backtest.portfolio_engine import (
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    PortfolioSession,
    PortfolioSignal,
)
from ashare_lab.backtest.portfolio_metrics import BenchmarkPoint, calculate_portfolio_metrics
from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.backtest.report_store import (
    PortfolioBacktestReportDescriptor,
    PortfolioBacktestReportStore,
    PortfolioBacktestReportStoreError,
)
from ashare_lab.portfolio import PortfolioRiskConfig

from .portfolio_backtest_support import bar, market, target, trading_date

ROOT = Path(__file__).parents[1]


def portfolio_report_fixture() -> PortfolioBacktestReport:
    symbol = "000001.SZ"
    sessions = (
        PortfolioSession(trading_date(0), (bar(symbol, 0, 10.0),)),
        PortfolioSession(trading_date(1), (bar(symbol, 1, 10.0),)),
    )
    risk = PortfolioRiskConfig(
        max_position_weight=0.50,
        minimum_cash_weight=0.05,
        maximum_turnover=1.0,
        maximum_volume_participation=1.0,
        maximum_industry_weight=1.0,
        maximum_concentration=1.0,
    )
    result = PortfolioBacktestEngine(
        PortfolioBacktestConfig(initial_cash=100_000.0, portfolio_risk=risk)
    ).run(sessions, (PortfolioSignal(target(0, ((symbol, 0.30),)), market((symbol,))),))
    metrics = calculate_portfolio_metrics(
        result,
        tuple(BenchmarkPoint(item.trading_date, 5_000.0) for item in sessions),
    )
    return PortfolioBacktestReport(
        target_artifact_id="portfolio_targets_" + "a" * 64,
        factor_report_id="factor_report_" + "b" * 64,
        dataset_snapshot_id="ds_abc123",
        market_schema_manifest_id="schema_" + "c" * 64,
        benchmark_schema_manifest_id="schema_" + "d" * 64,
        source_snapshot_ids=("snapshot_daily", "snapshot_benchmark"),
        benchmark_symbol="000905.SH",
        benchmark_price_basis="raw_open",
        cost_rule_version="china_a_cost_v1",
        risk_rule_version="portfolio_risk_v1",
        final_test_runs=0,
        result=result,
        metrics=metrics,
    )


def test_portfolio_backtest_report_is_content_addressed(tmp_path: Path) -> None:
    # Given: one complete real-engine report with frozen provenance.
    report = portfolio_report_fixture()
    store = PortfolioBacktestReportStore(tmp_path)

    # When: identical bytes are published twice.
    descriptors = (store.write(report), store.write(report))

    # Then: the immutable identity and verified report are reused.
    assert descriptors[0] == descriptors[1]
    assert store.read(descriptors[0]) == report


def test_portfolio_backtest_schema_documents_provenance_and_holdout_seal() -> None:
    # Given: the committed machine schema and its immutable trust boundary.
    document = json.loads(
        (ROOT / "schemas" / "portfolio_backtest_report_v1.json").read_text(encoding="utf-8")
    )

    # When: root fields are compared with the report model.
    required = set(document["required"])

    # Then: every provenance field, including final-test count, is mandatory.
    assert required == set(PortfolioBacktestReport.model_fields)


def test_portfolio_backtest_store_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: a valid report identity relabeled to an arbitrary path.
    store = PortfolioBacktestReportStore(tmp_path)
    descriptor = store.write(portfolio_report_fixture())
    crossed = descriptor.model_copy(update={"report_path": tmp_path / "other.json"})

    # When / Then: report bytes cannot be read outside their fixed directory.
    with pytest.raises(PortfolioBacktestReportStoreError, match="boundary"):
        store.read(crossed)


def test_portfolio_backtest_store_rejects_invalid_bytes(tmp_path: Path) -> None:
    # Given: a persisted report replaced with malformed bytes.
    store = PortfolioBacktestReportStore(tmp_path)
    descriptor = store.write(portfolio_report_fixture())
    descriptor.report_path.write_text("{}\n", encoding="utf-8")

    # When / Then: malformed bytes fail before they can retain report identity.
    with pytest.raises(PortfolioBacktestReportStoreError, match="missing or invalid"):
        store.read(descriptor)


def test_portfolio_backtest_store_rejects_mismatched_digest(tmp_path: Path) -> None:
    # Given: a valid report descriptor relabeled with a false digest.
    store = PortfolioBacktestReportStore(tmp_path)
    descriptor = store.write(portfolio_report_fixture())
    mismatched = PortfolioBacktestReportDescriptor(
        report_id=descriptor.report_id,
        report_path=descriptor.report_path,
        data_sha256="f" * 64,
    )

    # When / Then: valid bytes cannot be claimed by a different content digest.
    with pytest.raises(PortfolioBacktestReportStoreError, match="bytes differ"):
        store.read(mismatched)
