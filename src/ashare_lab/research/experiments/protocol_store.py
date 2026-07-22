"""Append-only storage for preregistered model experiment protocols."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ashare_lab.research.experiments.protocol_identity import (
    ModelProtocolIdentityError,
    validate_model_protocol,
)
from ashare_lab.research.experiments.protocol_models import ModelExperimentProtocol


class ModelProtocolDescriptor(BaseModel):
    """Verified path and byte identity for one immutable protocol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_id: str = Field(pattern=r"^model_protocol_[0-9a-f]{64}$")
    manifest_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelProtocolStoreError(Exception):
    """A model protocol is missing, altered, or crosses its ledger boundary."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable store failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the store boundary and concrete blocker."""
        return f"model_protocol_store: {self.detail}"


class ModelProtocolStore:
    """Atomically preregister protocols without overwriting an identity."""

    def __init__(self, root: Path) -> None:
        """Bind the store to one artifact root."""
        self._root = root / "model_protocols"

    def write(self, protocol: ModelExperimentProtocol) -> ModelProtocolDescriptor:
        """Append one protocol or verify an identical registration."""
        _validate(protocol)
        content = f"{protocol.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        directory = self._root / protocol.protocol_id
        descriptor = ModelProtocolDescriptor(
            protocol_id=protocol.protocol_id,
            manifest_path=directory / "manifest.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != protocol:
                detail = "existing model protocol content differs"
                raise ModelProtocolStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "manifest.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: ModelProtocolDescriptor) -> ModelExperimentProtocol:
        """Verify path, schema, bytes, and content-derived protocol identity."""
        expected = self._root / descriptor.protocol_id / "manifest.json"
        if descriptor.manifest_path != expected:
            detail = "descriptor crosses model protocol boundary"
            raise ModelProtocolStoreError(detail)
        try:
            content = descriptor.manifest_path.read_bytes()
            protocol = ModelExperimentProtocol.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "model protocol manifest is missing or invalid"
            raise ModelProtocolStoreError(detail) from error
        _validate(protocol)
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or protocol.protocol_id != descriptor.protocol_id:
            detail = "model protocol bytes differ from descriptor"
            raise ModelProtocolStoreError(detail)
        return protocol


def _validate(protocol: ModelExperimentProtocol) -> None:
    try:
        validate_model_protocol(protocol)
    except ModelProtocolIdentityError as error:
        raise ModelProtocolStoreError(error.detail) from error
