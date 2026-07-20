from datetime import UTC, date, datetime

import pytest

from ashare_lab.domain.market import MarketBar, PriceBasis, Symbol
from ashare_lab.research.features.market.models import MarketFactorObservation
from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleReadResult,
    MarketBundleRejection,
)
from ashare_lab.research.labels.models import BenchmarkOpenObservation
from ashare_lab.services.portfolio_backtest import (
    PortfolioBacktestAssemblyError,
    build_portfolio_backtest_inputs,
)

from .test_portfolio_runtime import single_factor_batch


def market_observation(symbol: str, day: date, price: float) -> MarketFactorObservation:
    return MarketFactorObservation(
        bar=MarketBar(
            symbol=Symbol(symbol),
            trading_date=day,
            available_at=datetime(day.year, day.month, day.day, 16, tzinfo=UTC),
            price_basis=PriceBasis.RAW,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=100_000,
            previous_close=price,
            limit_up=price * 1.1,
            limit_down=price * 0.9,
            is_suspended=False,
        ),
        adjustment_factor=1.0,
        turnover_rate=1.0,
        amount_cny=10_000_000.0,
        total_mv_ten_thousand_cny=1_000_000.0,
        pe_ttm=10.0,
        pb=1.0,
        ps_ttm=1.0,
        dv_ttm_percent=1.0,
        source_artifact_ids=(f"record_{symbol}_{day:%Y%m%d}",),
        source_snapshot_ids=(f"snapshot_{symbol}_{day:%Y%m%d}",),
    )


def benchmark_observation(day: date, price: float) -> BenchmarkOpenObservation:
    return BenchmarkOpenObservation(
        symbol="000905.SH",
        trading_date=day,
        open_price=price,
        available_at=datetime(day.year, day.month, day.day, 16, tzinfo=UTC),
        source_snapshot_id=f"snapshot_benchmark_{day:%Y%m%d}",
        source_row_sha256="a" * 64,
    )


def test_backtest_inputs_keep_raw_prices_share_volume_and_next_open_clock() -> None:
    # Given: one target batch and two complete DatasetSpec-bound market sessions.
    batch = single_factor_batch()
    decision = batch.records[0].decision_date
    next_day = date(decision.year, decision.month, decision.day + 1)
    symbols = tuple(item.symbol for item in batch.records[0].positions)
    observations = tuple(
        market_observation(symbol, day, 10.0) for day in (decision, next_day) for symbol in symbols
    )
    market = MarketBundleReadResult(observations, (), ())

    # When: label-free targets are assembled for the real engine boundary.
    inputs = build_portfolio_backtest_inputs(
        batch,
        (decision, next_day),
        market,
        (
            benchmark_observation(decision, 5_000.0),
            benchmark_observation(next_day, 5_010.0),
        ),
    )

    # Then: raw execution bars, share volume, and close-to-next-open ordering survive.
    assert inputs.sessions[0].bars[0].price_basis is PriceBasis.RAW
    assert inputs.sessions[0].bars[0].volume == 100_000
    assert inputs.signals[0].target.decision_date == decision
    assert inputs.sessions[1].trading_date == next_day
    assert inputs.signals[0].market[0].industry is None
    assert tuple(item.trading_date for item in inputs.benchmark) == (decision, next_day)


def test_backtest_inputs_fail_closed_on_incomplete_market_bundle() -> None:
    # Given: a target symbol whose raw daily anchor lacks a required market chain.
    batch = single_factor_batch()
    decision = batch.records[0].decision_date
    rejected = MarketBundleReadResult(
        (),
        (MarketBundleRejection(batch.records[0].positions[0].symbol, decision, "MISSING_LIMIT"),),
        (),
    )

    # When / Then: no partial session or selected-subset backtest can be assembled.
    with pytest.raises(PortfolioBacktestAssemblyError, match="incomplete market bundle"):
        build_portfolio_backtest_inputs(batch, (decision,), rejected, ())


def test_backtest_inputs_reject_duplicate_bars() -> None:
    # Given: one target session with a duplicate natural key.
    batch = single_factor_batch()
    decision = batch.records[0].decision_date
    symbols = tuple(item.symbol for item in batch.records[0].positions)
    rows = tuple(market_observation(symbol, decision, 10.0) for symbol in symbols)
    duplicated = MarketBundleReadResult((*rows, rows[0]), (), ())

    # When / Then: arbitrary canonical row selection is forbidden.
    with pytest.raises(PortfolioBacktestAssemblyError, match="duplicate market bar"):
        build_portfolio_backtest_inputs(
            batch,
            (decision,),
            duplicated,
            (benchmark_observation(decision, 5_000.0),),
        )


def test_backtest_inputs_reject_misaligned_benchmark() -> None:
    # Given: complete market rows but no same-date benchmark observation.
    batch = single_factor_batch()
    decision = batch.records[0].decision_date
    symbols = tuple(item.symbol for item in batch.records[0].positions)
    rows = tuple(market_observation(symbol, decision, 10.0) for symbol in symbols)
    complete = MarketBundleReadResult(rows, (), ())

    # When / Then: benchmark omission cannot shorten the reported equity curve.
    with pytest.raises(PortfolioBacktestAssemblyError, match="benchmark observations"):
        build_portfolio_backtest_inputs(batch, (decision,), complete, ())
