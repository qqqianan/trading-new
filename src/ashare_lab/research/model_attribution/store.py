"""Atomic content-addressed storage for model attribution reports."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ashare_lab.research.model_attribution.models import ModelPerformanceAttributionReport


class ModelAttributionDescriptor(BaseModel):
    """Verified reference to one immutable attribution report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str = Field(pattern=r"^model_attribution_[0-9a-f]{64}$")
    report_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelAttributionStoreError(Exception):
    """An attribution report is missing, altered, or outside its fixed directory."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable store failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the store boundary and concrete blocker."""
        return f"model_attribution_store: {self.detail}"


class ModelAttributionStore:
    """Publish attribution reports without overwriting an existing identity."""

    def __init__(self, root: Path) -> None:
        """Bind the store to one artifact root."""
        self._root = root / "model_attributions"

    def write(self, report: ModelPerformanceAttributionReport) -> ModelAttributionDescriptor:
        """Atomically publish or verify one complete report."""
        content = f"{report.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        report_id = f"model_attribution_{digest}"
        directory = self._root / report_id
        descriptor = ModelAttributionDescriptor(
            report_id=report_id,
            report_path=directory / "report.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != report:
                detail = "existing attribution content differs"
                raise ModelAttributionStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "report.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: ModelAttributionDescriptor) -> ModelPerformanceAttributionReport:
        """Verify exact path, bytes, identity, and complete report schema."""
        expected = self._root / descriptor.report_id / "report.json"
        if descriptor.report_path != expected:
            detail = "descriptor crosses attribution boundary"
            raise ModelAttributionStoreError(detail)
        try:
            content = descriptor.report_path.read_bytes()
            report = ModelPerformanceAttributionReport.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "attribution report is missing or invalid"
            raise ModelAttributionStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or descriptor.report_id != (
            f"model_attribution_{digest}"
        ):
            detail = "attribution bytes differ from descriptor"
            raise ModelAttributionStoreError(detail)
        return report
