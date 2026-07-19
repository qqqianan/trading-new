"""Atomic content-addressed persistence for fold preprocessing manifests."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from ashare_lab.research.preprocessing.models import (
    FoldPreprocessingArtifact,
    FoldPreprocessorDescriptor,
)


class FoldPreprocessorStoreError(Exception):
    """A preprocessing manifest is missing, invalid, or altered."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed persistence failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the artifact boundary and concrete failure."""
        return f"preprocessor_artifact: {self.detail}"


class FoldPreprocessorStore:
    """Publish immutable fold parameters under their exact content identity."""

    def __init__(self, artifact_root: Path) -> None:
        """Bind the store to the caller-owned artifact root."""
        self._root = artifact_root / "preprocessor"

    def write(self, artifact: FoldPreprocessingArtifact) -> FoldPreprocessorDescriptor:
        """Atomically publish or verify one fitted fold artifact."""
        content = f"{artifact.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        artifact_id = f"preprocessor_artifact_{digest}"
        directory = self._root / artifact_id
        descriptor = FoldPreprocessorDescriptor(
            artifact_id=artifact_id,
            manifest_path=directory / "manifest.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != artifact:
                detail = "existing manifest content differs"
                raise FoldPreprocessorStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "manifest.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: FoldPreprocessorDescriptor) -> FoldPreprocessingArtifact:
        """Verify path, bytes, identity, and schema before returning parameters."""
        expected = self._root / descriptor.artifact_id / "manifest.json"
        if descriptor.manifest_path != expected:
            detail = "descriptor crosses preprocessor boundary"
            raise FoldPreprocessorStoreError(detail)
        try:
            content = descriptor.manifest_path.read_bytes()
            artifact = FoldPreprocessingArtifact.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "manifest is missing or invalid"
            raise FoldPreprocessorStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or descriptor.artifact_id != (
            f"preprocessor_artifact_{digest}"
        ):
            detail = "manifest bytes differ from descriptor"
            raise FoldPreprocessorStoreError(detail)
        return artifact
