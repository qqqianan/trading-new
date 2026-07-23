from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.code_identity import GitEvidence
from ashare_lab.research.experiments.portfolio_protocol_store import PortfolioProtocolStore
from ashare_lab.services import portfolio_protocol_runtime
from ashare_lab.services.portfolio_protocol_runtime import (
    PortfolioProtocolRuntimeError,
    run_factor_anchor_veto_preregistration,
)

from .test_model_attribution_runtime import publish_model_attribution_fixture


def test_portfolio_protocol_runtime_verifies_full_parent_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one real attribution chain and a reproducible Git identity.
    attribution, _diagnostic_id, model_id, baseline_id, model_backtest_id = (
        publish_model_attribution_fixture(tmp_path)
    )

    def git_evidence(_root: Path) -> GitEvidence:
        return GitEvidence(commit="c" * 40, is_clean=True)

    monkeypatch.setattr(portfolio_protocol_runtime, "load_git_evidence", git_evidence)

    # When: the protocol composition root resolves every immutable parent.
    descriptor = run_factor_anchor_veto_preregistration(
        tmp_path,
        attribution.report_id,
        datetime(2026, 7, 23, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "research_owner",
    )

    # Then: the protocol binds attribution, model, and both comparison backtests.
    protocol = PortfolioProtocolStore(tmp_path / "data" / "artifacts").read(descriptor)
    assert protocol.parent_attribution_report_id == attribution.report_id
    assert protocol.parent_model_id == model_id
    assert protocol.baseline_backtest_id == baseline_id
    assert protocol.model_backtest_id == model_backtest_id
    assert protocol.fresh_forward.final_holdout_access_permitted is False


def test_portfolio_protocol_runtime_translates_missing_parent_to_stable_blocker(
    tmp_path: Path,
) -> None:
    # Given: an artifact root without the requested attribution report.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: missing evidence is translated at the formal composition boundary.
    with pytest.raises(PortfolioProtocolRuntimeError, match="portfolio_protocol_runtime"):
        run_factor_anchor_veto_preregistration(
            tmp_path,
            "model_attribution_" + "a" * 64,
            datetime(2026, 7, 23, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            "research_owner",
        )
