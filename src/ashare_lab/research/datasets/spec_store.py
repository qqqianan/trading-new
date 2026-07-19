"""Atomic content-addressed persistence for logical DatasetSpec manifests."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from ashare_lab.research.datasets.spec import DatasetSpec


@dataclass(frozen=True, slots=True)
class DatasetSpecDescriptor:
    """Stable local reference to one immutable logical dataset manifest."""

    snapshot_id: str
    manifest_path: Path
    data_sha256: str


class DatasetSpecStoreError(Exception):
    """A logical dataset manifest is missing, invalid, or altered."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record one stable content mismatch detail."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the store rule and concrete identity detail."""
        return f"content_mismatch: {self.detail}"


class DatasetSpecStore:
    """Publish DatasetSpec JSON under its deterministic ds identity."""

    def __init__(self, artifact_root: Path) -> None:
        """Bind the store to the caller-owned research artifact root."""
        self._root = artifact_root / "dataset_spec"

    def write(self, spec: DatasetSpec) -> DatasetSpecDescriptor:
        """Atomically publish or verify one complete logical dataset."""
        content = f"{spec.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        final_directory = self._root / spec.snapshot_id
        descriptor = DatasetSpecDescriptor(
            spec.snapshot_id,
            final_directory / "manifest.json",
            digest,
        )
        if final_directory.exists():
            self._verify(descriptor, spec)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "manifest.json").write_bytes(content)
            temporary.replace(final_directory)
        return descriptor

    def read(self, descriptor: DatasetSpecDescriptor) -> DatasetSpec:
        """Read only an exact path whose bytes still match its descriptor."""
        expected = self._root / descriptor.snapshot_id / "manifest.json"
        if descriptor.manifest_path != expected:
            detail = f"descriptor crosses dataset_spec boundary: {descriptor.snapshot_id}"
            raise DatasetSpecStoreError(detail)
        try:
            content = descriptor.manifest_path.read_bytes()
            spec = DatasetSpec.model_validate_json(content)
        except (FileNotFoundError, ValidationError) as error:
            detail = f"invalid DatasetSpec manifest: {descriptor.snapshot_id}"
            raise DatasetSpecStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if spec.snapshot_id != descriptor.snapshot_id or digest != descriptor.data_sha256:
            detail = f"DatasetSpec bytes differ: {descriptor.snapshot_id}"
            raise DatasetSpecStoreError(detail)
        return spec

    def _verify(self, descriptor: DatasetSpecDescriptor, expected: DatasetSpec) -> None:
        actual = self.read(descriptor)
        if actual != expected:
            detail = f"DatasetSpec content differs: {descriptor.snapshot_id}"
            raise DatasetSpecStoreError(detail)
