"""Composition root for preregistering a factor-anchor Ridge-veto portfolio."""

from datetime import datetime
from pathlib import Path

from ashare_lab.code_identity import CodeIdentityError, load_git_evidence
from ashare_lab.research.experiments.portfolio_protocol_identity import (
    PortfolioProtocolRequest,
    create_factor_anchor_veto_protocol,
)
from ashare_lab.research.experiments.portfolio_protocol_store import (
    PortfolioProtocolDescriptor,
    PortfolioProtocolStore,
    PortfolioProtocolStoreError,
)
from ashare_lab.services.portfolio_protocol_evidence import (
    PortfolioProtocolEvidenceError,
    load_portfolio_protocol_evidence,
)


class PortfolioProtocolRuntimeError(Exception):
    """Frozen evidence cannot preregister the next portfolio experiment."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable runtime blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and concrete blocker."""
        return f"portfolio_protocol_runtime: {self.detail}"


def run_factor_anchor_veto_preregistration(
    project_root: Path,
    attribution_report_id: str,
    registered_at: datetime,
    registered_by: str,
) -> PortfolioProtocolDescriptor:
    """Freeze one portfolio experiment without building targets or opening holdout."""
    try:
        root = project_root / "data" / "artifacts"
        evidence = load_portfolio_protocol_evidence(root, attribution_report_id)
        attribution = evidence.attribution
        dataset = evidence.dataset
        baseline = evidence.baseline_backtest
        model_backtest = evidence.model_backtest
        protocol = create_factor_anchor_veto_protocol(
            PortfolioProtocolRequest(
                dataset_snapshot_id=dataset.snapshot_id,
                schema_manifest_id=dataset.schema_manifest_id,
                lineage_manifest_id=dataset.lineage_manifest_id,
                parent_attribution_report_id=attribution_report_id,
                parent_diagnostic_report_id=attribution.diagnostic_report_id,
                parent_model_id=evidence.model.model_id,
                prediction_artifact_sha256=evidence.model.prediction_artifact_sha256,
                baseline_target_artifact_id=baseline.target_artifact_id,
                baseline_backtest_id=attribution.baseline_backtest_id,
                model_target_artifact_id=model_backtest.target_artifact_id,
                model_backtest_id=attribution.model_backtest_id,
                registered_at=registered_at,
                registered_by=registered_by,
                code_commit=load_git_evidence(project_root).commit,
                rulebook_version=dataset.rulebook_version,
                cost_rule_version=baseline.cost_rule_version,
                risk_rule_version=baseline.risk_rule_version,
            )
        )
        return PortfolioProtocolStore(root).write(protocol)
    except (
        PortfolioProtocolEvidenceError,
        CodeIdentityError,
        PortfolioProtocolStoreError,
    ) as error:
        raise PortfolioProtocolRuntimeError(str(error)) from error
