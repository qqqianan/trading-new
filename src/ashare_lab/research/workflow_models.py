"""Immutable contracts for the ordered medium-horizon research workflow."""

import hashlib
import json
from datetime import date
from enum import StrEnum, unique

from pydantic import BaseModel, ConfigDict, Field


class FrozenWorkflowModel(BaseModel):
    """Strict immutable boundary for workflow files and reports."""

    model_config = ConfigDict(frozen=True, extra="forbid")


@unique
class ResearchStage(StrEnum):
    """Constitutional order of the complete research pipeline."""

    QUALIFY = "qualify"
    MATERIALIZE = "materialize"
    DIAGNOSE = "diagnose"
    PORTFOLIO = "portfolio"
    BACKTEST = "backtest"
    TRAIN = "train"


@unique
class StageStatus(StrEnum):
    """Closed workflow and stage outcomes."""

    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


@unique
class ResearchModelStatus(StrEnum):
    """Model disclosure states allowed in a research report."""

    NOT_TRAINED = "NOT_TRAINED"
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"


class ResearchRunRequest(FrozenWorkflowModel):
    """Frozen identities and disclosures shared by all workflow stages."""

    data_cutoff: date
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    schema_manifest_id: str = Field(pattern=r"^schema_[0-9a-f]+$")
    lineage_manifest_id: str = Field(pattern=r"^lineage_[0-9a-f]+$")
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rulebook_version: str = Field(min_length=1)
    database_name: str = Field(pattern=r"^ashare_quant$")
    universe_rule_version: str = Field(min_length=1)
    factor_formulas: tuple[str, ...] = Field(min_length=1)
    trial_ids: tuple[str, ...] = Field(min_length=1)
    cost_rule_version: str = Field(min_length=1)
    risk_rule_version: str = Field(min_length=1)
    worst_period: str = Field(min_length=1)
    model_status: ResearchModelStatus
    final_test_runs: int = Field(ge=0, le=0)


class StageRecord(FrozenWorkflowModel):
    """Observable artifact identities and failures from one stage."""

    stage: ResearchStage
    status: StageStatus
    artifact_ids: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


class ResearchAuditReport(FrozenWorkflowModel):
    """Complete machine report produced before any final-holdout access."""

    report_id: str = Field(pattern=r"^research_report_[0-9a-f]{64}$")
    status: StageStatus
    data_cutoff: date
    dataset_snapshot_id: str
    schema_manifest_id: str
    lineage_manifest_id: str
    git_commit: str
    uv_lock_sha256: str
    rulebook_version: str
    database_name: str
    universe_rule_version: str
    factor_formulas: tuple[str, ...]
    trial_ids: tuple[str, ...]
    cost_rule_version: str
    risk_rule_version: str
    worst_period: str
    failures: tuple[str, ...]
    model_status: ResearchModelStatus
    final_test_runs: int = Field(ge=0, le=0)
    stages: tuple[StageRecord, ...] = Field(min_length=1)
    investment_disclaimer: str


def build_research_report(
    request: ResearchRunRequest,
    stages: tuple[StageRecord, ...],
) -> ResearchAuditReport:
    """Content-address one complete development-only report."""
    failures = tuple(failure for stage in stages for failure in stage.failures)
    statuses = tuple(stage.status for stage in stages)
    status = (
        StageStatus.BLOCKED
        if StageStatus.BLOCKED in statuses
        else StageStatus.PLANNED
        if StageStatus.PLANNED in statuses
        else StageStatus.COMPLETED
    )
    draft = ResearchAuditReport(
        report_id=f"research_report_{'0' * 64}",
        status=status,
        data_cutoff=request.data_cutoff,
        dataset_snapshot_id=request.dataset_snapshot_id,
        schema_manifest_id=request.schema_manifest_id,
        lineage_manifest_id=request.lineage_manifest_id,
        git_commit=request.git_commit,
        uv_lock_sha256=request.uv_lock_sha256,
        rulebook_version=request.rulebook_version,
        database_name=request.database_name,
        universe_rule_version=request.universe_rule_version,
        factor_formulas=request.factor_formulas,
        trial_ids=request.trial_ids,
        cost_rule_version=request.cost_rule_version,
        risk_rule_version=request.risk_rule_version,
        worst_period=request.worst_period,
        failures=failures,
        model_status=request.model_status,
        final_test_runs=request.final_test_runs,
        stages=stages,
        investment_disclaimer="研究结果不构成投资建议, 不承诺收益。",
    )
    canonical = json.dumps(
        draft.model_dump(mode="json", exclude={"report_id"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    report_id = f"research_report_{hashlib.sha256(canonical.encode()).hexdigest()}"
    return draft.model_copy(update={"report_id": report_id})
