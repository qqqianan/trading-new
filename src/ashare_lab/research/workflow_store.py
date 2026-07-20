"""Atomic JSON and Chinese Markdown storage for research audit reports."""

from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ashare_lab.research.workflow_models import (
    ResearchAuditReport,
    ResearchRunRequest,
    build_research_report,
)


class ResearchReportDescriptor(BaseModel):
    """Local paths for one content-addressed bilingual report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str = Field(pattern=r"^research_report_[0-9a-f]{64}$")
    json_path: Path
    markdown_path: Path


class ResearchReportStoreError(Exception):
    """A report is missing, altered, or outside its content-addressed directory."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed report storage failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the report boundary and stable detail."""
        return f"research_report: {self.detail}"


class ResearchReportStore:
    """Publish deterministic machine and human reports without overwrite."""

    def __init__(self, root: Path) -> None:
        """Bind report output to a caller-owned artifact root."""
        self._root = root

    def write(self, report: ResearchAuditReport) -> ResearchReportDescriptor:
        """Atomically publish or verify an identical existing report."""
        _verify_identity(report)
        directory = self._root / report.report_id
        descriptor = ResearchReportDescriptor(
            report_id=report.report_id,
            json_path=directory / "report.json",
            markdown_path=directory / "report.zh-CN.md",
        )
        if directory.exists():
            if self.read(descriptor) != report:
                detail = "existing report differs from content identity"
                raise ResearchReportStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "report.json").write_text(
                f"{report.model_dump_json(indent=2)}\n",
                encoding="utf-8",
            )
            (temporary / "report.zh-CN.md").write_text(_markdown(report), encoding="utf-8")
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: ResearchReportDescriptor) -> ResearchAuditReport:
        """Verify fixed paths, schema, and report content identity."""
        directory = self._root / descriptor.report_id
        if (
            descriptor.json_path != directory / "report.json"
            or descriptor.markdown_path != directory / "report.zh-CN.md"
        ):
            detail = "descriptor crosses report boundary"
            raise ResearchReportStoreError(detail)
        try:
            report = ResearchAuditReport.model_validate_json(descriptor.json_path.read_bytes())
            markdown = descriptor.markdown_path.read_text(encoding="utf-8")
        except (OSError, ValidationError) as error:
            detail = "report files are missing or invalid"
            raise ResearchReportStoreError(detail) from error
        _verify_identity(report)
        if markdown != _markdown(report):
            detail = "Chinese report differs from machine report"
            raise ResearchReportStoreError(detail)
        return report


def _verify_identity(report: ResearchAuditReport) -> None:
    request = ResearchRunRequest(
        **report.model_dump(
            include={
                "data_cutoff",
                "dataset_snapshot_id",
                "schema_manifest_id",
                "lineage_manifest_id",
                "git_commit",
                "uv_lock_sha256",
                "rulebook_version",
                "database_name",
                "universe_rule_version",
                "factor_formulas",
                "trial_ids",
                "cost_rule_version",
                "risk_rule_version",
                "worst_period",
                "model_status",
                "final_test_runs",
            }
        )
    )
    if build_research_report(request, report.stages) != report:
        detail = "report identity does not match its contents"
        raise ResearchReportStoreError(detail)


def _markdown(report: ResearchAuditReport) -> str:
    stages = "\n".join(
        f"- `{item.stage.value}`: **{item.status.value}**"
        + (f", 产物: {', '.join(item.artifact_ids)}" if item.artifact_ids else "")
        for item in report.stages
    )
    formulas = "\n".join(f"- `{item}`" for item in report.factor_formulas)
    trials = "\n".join(f"- `{item}`" for item in report.trial_ids)
    failures = "\n".join(f"- {item}" for item in report.failures) or "- 无"
    return f"""# A 股中期选股研究审计报告

> {report.investment_disclaimer}

## 研究身份

- 数据截止: `{report.data_cutoff.isoformat()}`
- DatasetSpec: `{report.dataset_snapshot_id}`
- Schema: `{report.schema_manifest_id}`
- Lineage: `{report.lineage_manifest_id}`
- Git: `{report.git_commit}`
- 规则版本: `{report.rulebook_version}`
- 股票池规则: `{report.universe_rule_version}`
- 最终留出集运行次数: `{report.final_test_runs}`

## 阶段

{stages}

## 因子公式

{formulas}

## 全部试验

{trials}

## 成本与风控

- 成本规则: `{report.cost_rule_version}`
- 风控规则: `{report.risk_rule_version}`

## 最差区间

{report.worst_period}

## 失败与阻断

{failures}

## 模型状态

`{report.model_status.value}`
"""
