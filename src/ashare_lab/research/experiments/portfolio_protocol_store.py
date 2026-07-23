"""Atomic content-addressed storage for portfolio experiment protocols."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ashare_lab.research.experiments.portfolio_protocol_identity import (
    PortfolioProtocolIdentityError,
    validate_portfolio_protocol,
)
from ashare_lab.research.experiments.portfolio_protocol_models import (
    PortfolioExperimentProtocol,
)


class PortfolioProtocolDescriptor(BaseModel):
    """Verified reference to one immutable portfolio protocol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_id: str = Field(pattern=r"^portfolio_protocol_[0-9a-f]{64}$")
    manifest_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PortfolioProtocolStoreError(Exception):
    """A protocol is missing, altered, or outside its fixed directory."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable store failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the store boundary and concrete blocker."""
        return f"portfolio_protocol_store: {self.detail}"


class PortfolioProtocolStore:
    """Publish protocols without overwriting an existing identity."""

    def __init__(self, root: Path) -> None:
        """Bind the store to one artifact root."""
        self._root = root / "portfolio_protocols"

    def write(self, protocol: PortfolioExperimentProtocol) -> PortfolioProtocolDescriptor:
        """Atomically publish or verify one complete protocol."""
        validate_portfolio_protocol(protocol)
        content = f"{protocol.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        directory = self._root / protocol.protocol_id
        descriptor = PortfolioProtocolDescriptor(
            protocol_id=protocol.protocol_id,
            manifest_path=directory / "manifest.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != protocol:
                detail = "existing portfolio protocol content differs"
                raise PortfolioProtocolStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "manifest.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: PortfolioProtocolDescriptor) -> PortfolioExperimentProtocol:
        """Verify exact path, bytes, schema, content identity, and descriptor digest."""
        expected = self._root / descriptor.protocol_id / "manifest.json"
        if descriptor.manifest_path != expected:
            detail = "descriptor crosses portfolio protocol boundary"
            raise PortfolioProtocolStoreError(detail)
        try:
            content = descriptor.manifest_path.read_bytes()
            protocol = PortfolioExperimentProtocol.model_validate_json(content)
            validate_portfolio_protocol(protocol)
        except (OSError, ValidationError, PortfolioProtocolIdentityError) as error:
            detail = "portfolio protocol is missing or invalid"
            raise PortfolioProtocolStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or descriptor.protocol_id != protocol.protocol_id:
            detail = "portfolio protocol bytes differ from descriptor"
            raise PortfolioProtocolStoreError(detail)
        return protocol
