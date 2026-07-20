"""Governed portfolio comparison for one post-hoc model diagnosis."""

from dataclasses import dataclass
from math import exp, log
from typing import Final

import numpy as np

from ashare_lab.backtest.report_models import PortfolioBacktestReport
from ashare_lab.domain.risk import RiskAction
from ashare_lab.portfolio.research_models import PortfolioTargetBatch
from ashare_lab.research.model_diagnostics.models import BacktestComparison

_TRADING_DAYS: Final = 252


class PortfolioDiagnosticError(Exception):
    """Portfolio artifacts are not comparable development evidence."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable portfolio diagnostic blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the comparison boundary and concrete blocker."""
        return f"portfolio_diagnostic: {self.detail}"


@dataclass(frozen=True, slots=True)
class PortfolioComparisonInput:
    """Exact baseline and model portfolio evidence to compare."""

    baseline_id: str
    baseline: PortfolioBacktestReport
    model_id: str
    model: PortfolioBacktestReport
    baseline_targets: PortfolioTargetBatch
    model_targets: PortfolioTargetBatch


def portfolio_comparison(request: PortfolioComparisonInput) -> BacktestComparison:
    """Compare exact targets and cost-aware reports without selecting a winner."""
    baseline = request.baseline
    model = request.model
    overlaps = _target_overlaps(request.baseline_targets, request.model_targets)
    halt = next(
        (
            event
            for event in model.result.risk_events
            if event.action is RiskAction.HALT_AND_LIQUIDATE
        ),
        None,
    )
    return BacktestComparison(
        baseline_backtest_id=request.baseline_id,
        model_backtest_id=request.model_id,
        baseline_total_return=baseline.metrics.total_return,
        model_total_return=model.metrics.total_return,
        baseline_annualized_return=_annualized_return(baseline),
        model_annualized_return=_annualized_return(model),
        baseline_sharpe=baseline.metrics.sharpe_ratio,
        model_sharpe=model.metrics.sharpe_ratio,
        baseline_max_drawdown=baseline.metrics.max_drawdown,
        model_max_drawdown=model.metrics.max_drawdown,
        baseline_turnover=baseline.metrics.turnover,
        model_turnover=model.metrics.turnover,
        baseline_fees=baseline.metrics.total_fees,
        model_fees=model.metrics.total_fees,
        baseline_pending_orders=baseline.metrics.pending_order_count,
        model_pending_orders=model.metrics.pending_order_count,
        baseline_trades=len(baseline.result.trades),
        model_trades=len(model.result.trades),
        mean_top30_overlap=float(np.mean(overlaps)),
        minimum_top30_overlap=float(np.min(overlaps)),
        risk_halt_date=None if halt is None else halt.trading_date,
        risk_halt_rule=None if halt is None else halt.rule.value,
    )


def _target_overlaps(
    baseline: PortfolioTargetBatch,
    model: PortfolioTargetBatch,
) -> tuple[float, ...]:
    baseline_index = {item.decision_date: item for item in baseline.records}
    model_index = {item.decision_date: item for item in model.records}
    if len(baseline_index) != len(baseline.records) or baseline_index.keys() != model_index.keys():
        detail = "baseline and model target dates differ or are duplicated"
        raise PortfolioDiagnosticError(detail)
    values: list[float] = []
    for day, baseline_record in baseline_index.items():
        left = {item.symbol for item in baseline_record.positions}
        right = {item.symbol for item in model_index[day].positions}
        denominator = max(len(left), len(right))
        if denominator == 0:
            detail = "target record contains no positions"
            raise PortfolioDiagnosticError(detail)
        values.append(len(left & right) / denominator)
    return tuple(values)


def _annualized_return(report: PortfolioBacktestReport) -> float:
    periods = len(report.result.equity_curve) - 1
    if periods <= 0 or report.metrics.total_return <= -1:
        detail = "backtest equity curve cannot produce annualized return"
        raise PortfolioDiagnosticError(detail)
    return exp(log(1 + report.metrics.total_return) * _TRADING_DAYS / periods) - 1
