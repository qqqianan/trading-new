"""Atomic content-addressed persistence for portfolio backtest reports."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ashare_lab.backtest.report_models import PortfolioBacktestReport


class PortfolioBacktestReportDescriptor(BaseModel):
    """Verified local reference to one immutable portfolio backtest report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str = Field(pattern=r"^portfolio_backtest_[0-9a-f]{64}$")
    report_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PortfolioBacktestReportStoreError(Exception):
    """A backtest report is missing, altered, or crosses its fixed directory."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable report-store failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the report-store boundary and concrete blocker."""
        return f"portfolio_backtest_store: {self.detail}"


class PortfolioBacktestReportStore:
    """Write complete reports without overwriting an existing identity."""

    def __init__(self, root: Path) -> None:
        """Bind the content-addressed portfolio backtest directory."""
        self._root = root / "portfolio_backtests"

    def write(
        self,
        report: PortfolioBacktestReport,
    ) -> PortfolioBacktestReportDescriptor:
        """Atomically publish or verify one complete report."""
        content = f"{report.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        report_id = f"portfolio_backtest_{digest}"
        directory = self._root / report_id
        descriptor = PortfolioBacktestReportDescriptor(
            report_id=report_id,
            report_path=directory / "report.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != report:
                detail = "existing portfolio backtest content differs"
                raise PortfolioBacktestReportStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "report.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(
        self,
        descriptor: PortfolioBacktestReportDescriptor,
    ) -> PortfolioBacktestReport:
        """Verify exact path, bytes, identity, and complete report schema."""
        expected = self._root / descriptor.report_id / "report.json"
        if descriptor.report_path != expected:
            detail = "descriptor crosses portfolio backtest boundary"
            raise PortfolioBacktestReportStoreError(detail)
        try:
            content = descriptor.report_path.read_bytes()
            report = PortfolioBacktestReport.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "portfolio backtest report is missing or invalid"
            raise PortfolioBacktestReportStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or descriptor.report_id != (
            f"portfolio_backtest_{digest}"
        ):
            detail = "portfolio backtest bytes differ from descriptor"
            raise PortfolioBacktestReportStoreError(detail)
        return report
