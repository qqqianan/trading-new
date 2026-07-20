"""Atomic content-addressed persistence for training evidence documents."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel

from ashare_lab.research.model_evidence import ContentDocumentDescriptor


class TrainingDocumentStoreError(Exception):
    """A training evidence document conflicts with immutable stored bytes."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed immutable-document failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the evidence storage boundary and blocker."""
        return f"training_document: {self.detail}"


class TrainingDocumentStore:
    """Publish typed JSON evidence under its exact byte identity."""

    def __init__(self, root: Path) -> None:
        """Bind documents to one artifact root."""
        self._root = root

    def write(self, kind: str, document: BaseModel) -> ContentDocumentDescriptor:
        """Write canonical JSON once or verify the existing immutable bytes."""
        content = f"{document.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        directory = self._root / kind / f"{kind}_{digest}"
        path = directory / "manifest.json"
        descriptor = ContentDocumentDescriptor(path=path, data_sha256=digest)
        if directory.exists():
            try:
                existing = path.read_bytes()
            except OSError as error:
                detail = f"cannot read {kind}"
                raise TrainingDocumentStoreError(detail) from error
            if existing != content:
                detail = f"existing {kind} bytes differ"
                raise TrainingDocumentStoreError(detail)
            return descriptor
        (self._root / kind).mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root / kind) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "manifest.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor
