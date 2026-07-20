"""Atomic persistence for complete development portfolio targets."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import Field, ValidationError

from ashare_lab.portfolio.research_models import (
    FrozenPortfolioModel,
    PortfolioTargetBatch,
)


class PortfolioTargetDescriptor(FrozenPortfolioModel):
    """Verified local reference to one immutable target batch."""

    artifact_id: str = Field(pattern=r"^portfolio_targets_[0-9a-f]{64}$")
    artifact_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PortfolioTargetStoreError(Exception):
    """A target batch is missing, altered, or crosses its storage boundary."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable target-store failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the target-store boundary and concrete blocker."""
        return f"portfolio_target_store: {self.detail}"


class PortfolioTargetStore:
    """Write complete target batches without overwriting existing identities."""

    def __init__(self, root: Path) -> None:
        """Bind the content-addressed portfolio target directory."""
        self._root = root / "portfolio_targets"

    def write(self, batch: PortfolioTargetBatch) -> PortfolioTargetDescriptor:
        """Atomically publish or verify one complete target batch."""
        content = f"{batch.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        artifact_id = f"portfolio_targets_{digest}"
        directory = self._root / artifact_id
        descriptor = PortfolioTargetDescriptor(
            artifact_id=artifact_id,
            artifact_path=directory / "targets.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != batch:
                detail = "existing target batch content differs"
                raise PortfolioTargetStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "targets.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: PortfolioTargetDescriptor) -> PortfolioTargetBatch:
        """Verify exact path, bytes, identity, and complete target schema."""
        expected = self._root / descriptor.artifact_id / "targets.json"
        if descriptor.artifact_path != expected:
            detail = "descriptor crosses portfolio target boundary"
            raise PortfolioTargetStoreError(detail)
        try:
            content = descriptor.artifact_path.read_bytes()
            batch = PortfolioTargetBatch.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "portfolio target batch is missing or invalid"
            raise PortfolioTargetStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or descriptor.artifact_id != (
            f"portfolio_targets_{digest}"
        ):
            detail = "portfolio target bytes differ from descriptor"
            raise PortfolioTargetStoreError(detail)
        return batch
