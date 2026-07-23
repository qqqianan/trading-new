import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from ashare_lab.research.experiments.portfolio_protocol_identity import (
    PortfolioProtocolRequest,
    create_factor_anchor_veto_protocol,
    validate_portfolio_protocol,
)
from ashare_lab.research.experiments.portfolio_protocol_models import (
    FactorAnchorVetoRule,
    FreshForwardPolicy,
    PortfolioExperimentProtocol,
    PortfolioPromotionGates,
)
from ashare_lab.research.experiments.portfolio_protocol_store import (
    PortfolioProtocolStore,
    PortfolioProtocolStoreError,
)

ROOT = Path(__file__).parents[1]


def portfolio_protocol_request_fixture() -> PortfolioProtocolRequest:
    """Return one complete verified input boundary for adjacent tests."""
    return PortfolioProtocolRequest(
        dataset_snapshot_id="ds_abc123",
        schema_manifest_id="schema_" + "1" * 64,
        lineage_manifest_id="lineage_" + "2" * 64,
        parent_attribution_report_id="model_attribution_" + "3" * 64,
        parent_diagnostic_report_id="model_diagnostic_" + "4" * 64,
        parent_model_id="ridge_model_" + "5" * 64,
        prediction_artifact_sha256="6" * 64,
        baseline_target_artifact_id="portfolio_targets_" + "7" * 64,
        baseline_backtest_id="portfolio_backtest_" + "8" * 64,
        model_target_artifact_id="portfolio_targets_" + "9" * 64,
        model_backtest_id="portfolio_backtest_" + "a" * 64,
        registered_at=datetime(2026, 7, 23, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        registered_by="research_owner",
        code_commit="b" * 40,
        rulebook_version="1.0.0",
        cost_rule_version="cost_v1",
        risk_rule_version="risk_v1",
    )


def test_factor_anchor_veto_protocol_freezes_rule_and_fresh_forward_policy() -> None:
    # Given: exact parent attribution, data, model, targets, backtests, and code identities.
    request = portfolio_protocol_request_fixture()

    # When: the new portfolio experiment is preregistered.
    protocol = create_factor_anchor_veto_protocol(request)

    # Then: the non-optimized rule and honest future evidence boundary are immutable.
    assert protocol.protocol_id.startswith("portfolio_protocol_")
    assert protocol.candidate_rule.veto_quantile == 0.2
    assert protocol.candidate_rule.maximum_positions == 30
    assert protocol.fresh_forward.start_date == date(2026, 7, 24)
    assert protocol.fresh_forward.minimum_decision_dates == 26
    assert protocol.fresh_forward.final_holdout_access_permitted is False
    assert protocol.evidence_classification == "REUSED_DEVELOPMENT_NOT_OUT_OF_SAMPLE"
    assert protocol.status == "PREREGISTERED_NOT_IMPLEMENTED"
    validate_portfolio_protocol(protocol)


def test_portfolio_protocol_rejects_registration_after_fresh_forward_start() -> None:
    # Given: a request registered after the fixed fresh-forward observation begins.
    request = portfolio_protocol_request_fixture().model_copy(
        update={
            "registered_at": datetime(
                2026,
                7,
                24,
                9,
                0,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            )
        }
    )

    # When / Then: future evidence cannot be backdated into a preregistration.
    with pytest.raises(ValidationError, match="fresh-forward"):
        create_factor_anchor_veto_protocol(request)


def test_portfolio_protocol_store_is_content_addressed_and_detects_tampering(
    tmp_path: Path,
) -> None:
    # Given: one immutable protocol published twice.
    protocol = create_factor_anchor_veto_protocol(portfolio_protocol_request_fixture())
    store = PortfolioProtocolStore(tmp_path)

    # When: identical content is published repeatedly.
    descriptors = (store.write(protocol), store.write(protocol))

    # Then: identity is stable and modified bytes cannot retain it.
    assert descriptors[0] == descriptors[1]
    descriptors[0].manifest_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PortfolioProtocolStoreError, match="missing or invalid"):
        store.read(descriptors[0])


def test_portfolio_protocol_schema_documents_every_field() -> None:
    # Given: the committed machine schema for portfolio experiment preregistration.
    document = json.loads(
        (ROOT / "schemas" / "portfolio_experiment_protocol_v1.json").read_text(encoding="utf-8")
    )

    # When: schema requirements are compared with every persisted trust boundary.
    required = (
        set(document["required"]),
        set(document["$defs"]["FactorAnchorVetoRule"]["required"]),
        set(document["$defs"]["FreshForwardPolicy"]["required"]),
        set(document["$defs"]["PortfolioPromotionGates"]["required"]),
    )

    # Then: no protocol field or nested policy remains undocumented.
    assert required == (
        set(PortfolioExperimentProtocol.model_fields),
        set(FactorAnchorVetoRule.model_fields),
        set(FreshForwardPolicy.model_fields),
        set(PortfolioPromotionGates.model_fields),
    )
