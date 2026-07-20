"""Strict ordered orchestration for the auditable research workflow."""

from typing import Protocol

from ashare_lab.research.workflow_models import (
    ResearchAuditReport,
    ResearchRunRequest,
    ResearchStage,
    StageRecord,
    StageStatus,
    build_research_report,
)


class ResearchPipeline(Protocol):
    """Concrete stage adapter invoked only by the workflow service."""

    def execute(self, stage: ResearchStage, request: ResearchRunRequest) -> StageRecord:
        """Execute exactly one governed stage and return its immutable record."""
        ...


class ResearchWorkflowError(Exception):
    """A stage adapter returned an incoherent stage identity."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one orchestration contract violation."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the workflow boundary and stable detail."""
        return f"research_workflow: {self.detail}"


class ResearchWorkflowService:
    """Run stages in constitutional order and stop after the first blocker."""

    def __init__(self, pipeline: ResearchPipeline) -> None:
        """Bind one concrete composition root behind the ordered service."""
        self._pipeline = pipeline

    def run(self, request: ResearchRunRequest) -> ResearchAuditReport:
        """Execute every reachable stage without final-holdout authority."""
        records: list[StageRecord] = []
        for stage in ResearchStage:
            record = self._pipeline.execute(stage, request)
            if record.stage is not stage:
                detail = (
                    f"stage adapter returned {record.stage.value} while executing {stage.value}"
                )
                raise ResearchWorkflowError(detail)
            records.append(record)
            if record.status is StageStatus.BLOCKED:
                break
        return build_research_report(request, tuple(records))
