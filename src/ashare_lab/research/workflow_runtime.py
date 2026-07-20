"""Composition helpers for a truthful development-only workflow dry run."""

from datetime import date
from pathlib import Path

from pydantic import ValidationError

from ashare_lab.research.datasets.spec import DatasetSpec
from ashare_lab.research.experiments.trial_models import TrialBatch
from ashare_lab.research.features.financial.catalog import financial_factor_catalog
from ashare_lab.research.features.market.catalog import market_factor_catalog
from ashare_lab.research.preflight import ResearchIdentity
from ashare_lab.research.workflow_models import (
    ResearchModelStatus,
    ResearchRunRequest,
    ResearchStage,
    StageRecord,
    StageStatus,
)


class WorkflowRuntimeError(Exception):
    """Required frozen artifacts cannot form a workflow request."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one stable runtime configuration blocker."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the runtime boundary and stable detail."""
        return f"workflow_runtime: {self.detail}"


class DryRunResearchPipeline:
    """Record the immutable plan without executing data, backtest, or training code."""

    def execute(self, stage: ResearchStage, request: ResearchRunRequest) -> StageRecord:
        """Declare one reachable stage while keeping final holdout sealed."""
        if request.final_test_runs != 0:
            detail = "dry-run cannot consume final-holdout access"
            raise WorkflowRuntimeError(detail)
        return StageRecord(stage=stage, status=StageStatus.PLANNED)


def load_dry_run_request(project_root: Path, identity: ResearchIdentity) -> ResearchRunRequest:
    """Read the sole DatasetSpec and trial ledger for a reproducible plan."""
    artifact_root = project_root / "data" / "artifacts"
    dataset_path = _sole_path(artifact_root / "dataset_spec", "ds_*/manifest.json", "DatasetSpec")
    trial_path = _sole_path(
        artifact_root / "trial_ledger",
        "trial_batch_*/manifest.json",
        "trial batch",
    )
    try:
        spec = DatasetSpec.model_validate_json(dataset_path.read_bytes())
        batch = TrialBatch.model_validate_json(trial_path.read_bytes())
    except (OSError, ValidationError) as error:
        detail = "DatasetSpec or trial batch is missing or invalid"
        raise WorkflowRuntimeError(detail) from error
    if batch.dataset_snapshot_id != spec.snapshot_id:
        detail = "trial batch does not belong to the frozen DatasetSpec"
        raise WorkflowRuntimeError(detail)
    definitions = (*market_factor_catalog(), *financial_factor_catalog())
    formulas = tuple(
        f"{item.name} <- {','.join(item.source_fields)}; lookback={item.lookback_trading_days}"
        for item in definitions
    )
    return ResearchRunRequest(
        data_cutoff=min(spec.end_date, date(2024, 12, 31)),
        dataset_snapshot_id=spec.snapshot_id,
        schema_manifest_id=spec.schema_manifest_id,
        lineage_manifest_id=spec.lineage_manifest_id,
        git_commit=identity.git_commit,
        uv_lock_sha256=identity.uv_lock_sha256,
        rulebook_version=identity.rulebook_version,
        database_name=identity.database_name,
        universe_rule_version=spec.universe_version,
        factor_formulas=formulas,
        trial_ids=tuple(item.trial_id for item in batch.trials),
        cost_rule_version="china_a_cost_v1",
        risk_rule_version="portfolio_risk_v1",
        worst_period="尚未执行真实组合回测, 不得选择性披露区间。",
        model_status=ResearchModelStatus.NOT_TRAINED,
        final_test_runs=0,
    )


def _sole_path(root: Path, pattern: str, label: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        detail = f"expected exactly one {label}, found {len(paths)}"
        raise WorkflowRuntimeError(detail)
    return paths[0]
