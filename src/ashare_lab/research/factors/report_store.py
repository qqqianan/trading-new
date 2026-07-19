"""Atomic content-addressed persistence for complete factor research reports."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import Field, ValidationError

from ashare_lab.research.factors.models import FrozenFactorModel
from ashare_lab.research.factors.selection import FactorResearchReport


class FactorReportDescriptor(FrozenFactorModel):
    """Verified local reference to one immutable factor report."""

    report_id: str = Field(pattern=r"^factor_report_[0-9a-f]{64}$")
    report_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FactorReportStore:
    """Publish complete reports without overwriting an existing identity."""

    def __init__(self, root: Path) -> None:
        """Bind reports to a caller-owned artifact root."""
        self._root = root / "factor_report"

    def write(self, report: FactorResearchReport) -> FactorReportDescriptor:
        """Atomically publish or verify one complete report."""
        content = f"{report.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        report_id = f"factor_report_{digest}"
        directory = self._root / report_id
        descriptor = FactorReportDescriptor(
            report_id=report_id,
            report_path=directory / "report.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != report:
                detail = "existing report content differs"
                raise FactorReportStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "report.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: FactorReportDescriptor) -> FactorResearchReport:
        """Verify exact path, bytes, identity, and complete report schema."""
        expected = self._root / descriptor.report_id / "report.json"
        if descriptor.report_path != expected:
            detail = "descriptor crosses factor report boundary"
            raise FactorReportStoreError(detail)
        try:
            content = descriptor.report_path.read_bytes()
            report = FactorResearchReport.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "factor report is missing or invalid"
            raise FactorReportStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or descriptor.report_id != f"factor_report_{digest}":
            detail = "factor report bytes differ from descriptor"
            raise FactorReportStoreError(detail)
        return report


class FactorReportStoreError(Exception):
    """A factor report is missing, altered, or crosses its storage boundary."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed factor report failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the report boundary and concrete failure."""
        return f"factor_report: {self.detail}"
