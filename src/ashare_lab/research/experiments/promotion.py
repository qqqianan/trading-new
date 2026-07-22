"""Evaluate preregistered model promotion gates over immutable diagnostics."""

from ashare_lab.research.experiments.promotion_models import (
    ModelPromotionEvaluation,
    PromotionDecision,
    PromotionGate,
    PromotionGateResult,
)
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol
from ashare_lab.research.model_diagnostics.models import ModelDiagnosticReport


def evaluate_model_promotion(
    protocol: ModelExperimentProtocol,
    diagnostic_report_id: str,
    diagnostic: ModelDiagnosticReport,
) -> ModelPromotionEvaluation:
    """Evaluate all development gates without opening the final holdout."""
    gates = protocol.promotion_gates
    portfolio = diagnostic.portfolio
    minimum_fold_rank_ic = min(item.mean_rank_ic for item in diagnostic.fold_segments)
    no_risk_halt = portfolio.risk_halt_date is None and portfolio.risk_halt_rule is None
    checks = (
        _metric_gate(
            PromotionGate.MEAN_RANK_IC,
            diagnostic.overall_rank_ic.mean_rank_ic,
            gates.minimum_mean_rank_ic,
        ),
        _metric_gate(
            PromotionGate.MINIMUM_FOLD_RANK_IC,
            minimum_fold_rank_ic,
            gates.minimum_fold_rank_ic,
        ),
        _metric_gate(
            PromotionGate.DIRECTION_CONSISTENCY,
            diagnostic.overall_rank_ic.direction_consistency,
            gates.minimum_direction_consistency,
        ),
        PromotionGateResult(
            gate=PromotionGate.TOTAL_RETURN_OUTPERFORMANCE,
            passed=portfolio.model_total_return > portfolio.baseline_total_return,
            observed=(
                f"model={portfolio.model_total_return};baseline={portfolio.baseline_total_return}"
            ),
            requirement="model>baseline",
        ),
        PromotionGateResult(
            gate=PromotionGate.SHARPE_OUTPERFORMANCE,
            passed=portfolio.model_sharpe > portfolio.baseline_sharpe,
            observed=f"model={portfolio.model_sharpe};baseline={portfolio.baseline_sharpe}",
            requirement="model>baseline",
        ),
        PromotionGateResult(
            gate=PromotionGate.NO_RISK_HALT,
            passed=no_risk_halt,
            observed=(
                "none"
                if no_risk_halt
                else f"date={portfolio.risk_halt_date};rule={portfolio.risk_halt_rule}"
            ),
            requirement="no_risk_halt",
        ),
        PromotionGateResult(
            gate=PromotionGate.COMPLETE_INDUSTRY_PIT,
            passed=diagnostic.industry_neutralization == "AVAILABLE",
            observed=diagnostic.industry_neutralization,
            requirement="AVAILABLE",
        ),
    )
    decision = (
        PromotionDecision.ELIGIBLE_FOR_MANUAL_AUTHORIZATION
        if all(item.passed for item in checks)
        else PromotionDecision.BLOCKED
    )
    return ModelPromotionEvaluation(
        protocol_id=protocol.protocol_id,
        model_id=diagnostic.model_id,
        diagnostic_report_id=diagnostic_report_id,
        dataset_snapshot_id=diagnostic.dataset_snapshot_id,
        checks=checks,
        decision=decision,
        final_holdout_authorized=False,
        model_status="DRAFT",
        final_test_runs=0,
    )


def _metric_gate(gate: PromotionGate, observed: float, minimum: float) -> PromotionGateResult:
    return PromotionGateResult(
        gate=gate,
        passed=observed >= minimum,
        observed=str(observed),
        requirement=f">={minimum}",
    )
