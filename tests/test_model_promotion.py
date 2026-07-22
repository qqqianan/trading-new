import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from ashare_lab.research.experiments.promotion import evaluate_model_promotion
from ashare_lab.research.experiments.promotion_models import (
    ModelPromotionEvaluation,
    PromotionDecision,
    PromotionGate,
    PromotionGateResult,
)
from ashare_lab.research.experiments.promotion_store import (
    PromotionEvaluationStore,
    PromotionEvaluationStoreError,
)
from ashare_lab.research.experiments.protocol_identity import create_rank_aligned_protocol
from ashare_lab.research.model_diagnostics.calculations import diagnose_ridge_model
from ashare_lab.research.model_diagnostics.models import ModelDiagnosticReport

from .test_model_diagnostics import model_diagnostic_input_fixture
from .test_model_protocol import protocol_request

DIAGNOSTIC_ID = "model_diagnostic_" + "d" * 64
ROOT = Path(__file__).parents[1]


def passing_diagnostic() -> ModelDiagnosticReport:
    report = diagnose_ridge_model(model_diagnostic_input_fixture())
    overall = report.overall_rank_ic.model_copy(
        update={"mean_rank_ic": 0.10, "direction_consistency": 0.75}
    )
    folds = tuple(item.model_copy(update={"mean_rank_ic": 0.05}) for item in report.fold_segments)
    portfolio = report.portfolio.model_copy(
        update={
            "baseline_total_return": 0.10,
            "model_total_return": 0.12,
            "baseline_sharpe": 0.50,
            "model_sharpe": 0.60,
            "risk_halt_date": None,
            "risk_halt_rule": None,
        }
    )
    return report.model_copy(
        update={
            "overall_rank_ic": overall,
            "fold_segments": folds,
            "portfolio": portfolio,
            "industry_neutralization": "AVAILABLE",
        }
    )


def test_model_promotion_requires_every_preregistered_development_gate() -> None:
    # Given: one diagnostic satisfying every frozen rank, portfolio, risk, and PIT condition.
    protocol = create_rank_aligned_protocol(protocol_request())

    # When: development evidence is evaluated without final-test access.
    evaluation = evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())

    # Then: it is only eligible for later manual authorization and remains a DRAFT.
    assert evaluation.decision is PromotionDecision.ELIGIBLE_FOR_MANUAL_AUTHORIZATION
    assert tuple(item.gate for item in evaluation.checks) == tuple(PromotionGate)
    assert all(item.passed for item in evaluation.checks)
    assert evaluation.final_holdout_authorized is False
    assert evaluation.model_status == "DRAFT"
    assert evaluation.final_test_runs == 0


def test_model_promotion_fails_closed_with_exact_failed_gate_evidence() -> None:
    # Given: otherwise passing evidence with weak rank stability and portfolio losses,
    # plus a risk halt and unavailable industry PIT.
    protocol = create_rank_aligned_protocol(protocol_request())
    passing = passing_diagnostic()
    weak_overall = passing.overall_rank_ic.model_copy(update={"direction_consistency": 0.50})
    weak_folds = (
        passing.fold_segments[0].model_copy(update={"mean_rank_ic": -0.01}),
        *passing.fold_segments[1:],
    )
    failed_portfolio = passing.portfolio.model_copy(
        update={
            "model_total_return": 0.05,
            "model_sharpe": 0.25,
            "risk_halt_date": date(2024, 1, 22),
            "risk_halt_rule": "max_drawdown",
        }
    )
    diagnostic = passing.model_copy(
        update={
            "overall_rank_ic": weak_overall,
            "fold_segments": weak_folds,
            "portfolio": failed_portfolio,
            "industry_neutralization": "UNAVAILABLE",
        }
    )

    # When: all gates are evaluated instead of stopping after the first failure.
    evaluation = evaluate_model_promotion(protocol, DIAGNOSTIC_ID, diagnostic)

    # Then: the report is blocked and discloses every failed preregistered condition.
    failed = {item.gate for item in evaluation.checks if not item.passed}
    assert evaluation.decision is PromotionDecision.BLOCKED
    assert failed == {
        PromotionGate.MINIMUM_FOLD_RANK_IC,
        PromotionGate.DIRECTION_CONSISTENCY,
        PromotionGate.TOTAL_RETURN_OUTPERFORMANCE,
        PromotionGate.SHARPE_OUTPERFORMANCE,
        PromotionGate.NO_RISK_HALT,
        PromotionGate.COMPLETE_INDUSTRY_PIT,
    }
    assert evaluation.final_holdout_authorized is False


def test_model_promotion_store_is_append_only_and_content_addressed(tmp_path: Path) -> None:
    # Given: one complete promotion decision and an empty artifact root.
    protocol = create_rank_aligned_protocol(protocol_request())
    evaluation = evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())
    store = PromotionEvaluationStore(tmp_path)

    # When: identical evidence is published twice.
    descriptors = (store.write(evaluation), store.write(evaluation))

    # Then: one stable identity is reused and exact bytes remain readable.
    assert descriptors[0] == descriptors[1]
    assert store.read(descriptors[0]) == evaluation
    assert len(tuple((tmp_path / "model_promotions").iterdir())) == 1


def test_model_promotion_schema_documents_every_persisted_field() -> None:
    # Given: the committed machine schema for development promotion evidence.
    document = json.loads(
        (ROOT / "schemas" / "model_promotion_evaluation_v1.json").read_text(encoding="utf-8")
    )

    # When: required fields are compared with both Pydantic trust boundaries.
    required = (
        set(document["required"]),
        set(document["$defs"]["PromotionGateResult"]["required"]),
    )

    # Then: no persisted decision or individual gate field is undocumented.
    assert required == (
        set(ModelPromotionEvaluation.model_fields),
        set(PromotionGateResult.model_fields),
    )


def test_model_promotion_rejects_decision_that_disagrees_with_gates() -> None:
    # Given: seven passing checks relabeled by a caller as blocked.
    protocol = create_rank_aligned_protocol(protocol_request())
    evaluation = evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())
    payload = evaluation.model_dump(mode="json")
    payload["decision"] = "BLOCKED"

    # When / Then: the trust boundary recomputes the only valid total decision.
    with pytest.raises(ValidationError, match="decision differs"):
        ModelPromotionEvaluation.model_validate(payload)


def test_model_promotion_rejects_duplicate_or_reordered_gate_set() -> None:
    # Given: a caller replaces the first canonical gate with a duplicate later gate.
    protocol = create_rank_aligned_protocol(protocol_request())
    evaluation = evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())
    payload = evaluation.model_dump(mode="json")
    payload["checks"][0]["gate"] = PromotionGate.SHARPE_OUTPERFORMANCE.value

    # When / Then: incomplete or reordered gate evidence cannot be persisted.
    with pytest.raises(ValidationError, match="canonical order"):
        ModelPromotionEvaluation.model_validate(payload)


def test_model_promotion_store_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: valid promotion evidence relabeled to an arbitrary path.
    protocol = create_rank_aligned_protocol(protocol_request())
    store = PromotionEvaluationStore(tmp_path)
    descriptor = store.write(
        evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())
    )
    crossed = descriptor.model_copy(update={"report_path": tmp_path / "other.json"})

    # When / Then: evidence cannot be read outside its content directory.
    with pytest.raises(PromotionEvaluationStoreError, match="boundary"):
        store.read(crossed)


def test_model_promotion_store_rejects_tampered_content(tmp_path: Path) -> None:
    # Given: a persisted report whose bytes are replaced after publication.
    protocol = create_rank_aligned_protocol(protocol_request())
    store = PromotionEvaluationStore(tmp_path)
    descriptor = store.write(
        evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())
    )
    descriptor.report_path.write_text("{}\n", encoding="utf-8")

    # When / Then: invalid content cannot retain its original identity.
    with pytest.raises(PromotionEvaluationStoreError, match="missing or invalid"):
        store.read(descriptor)


def test_model_promotion_store_rejects_false_digest(tmp_path: Path) -> None:
    # Given: valid bytes paired with a caller-substituted digest.
    protocol = create_rank_aligned_protocol(protocol_request())
    store = PromotionEvaluationStore(tmp_path)
    descriptor = store.write(
        evaluate_model_promotion(protocol, DIAGNOSTIC_ID, passing_diagnostic())
    )
    mismatched = descriptor.model_copy(update={"data_sha256": "f" * 64})

    # When / Then: the store recomputes content identity before returning evidence.
    with pytest.raises(PromotionEvaluationStoreError, match="bytes differ"):
        store.read(mismatched)
