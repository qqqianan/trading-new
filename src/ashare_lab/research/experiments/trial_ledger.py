"""Atomic append-only store for factor trials registered before diagnostics."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from ashare_lab.research.experiments.trial_identity import (
    TrialIdentityError,
    TrialRegistrationContext,
    create_trial_batch,
    validate_trial_identities,
)
from ashare_lab.research.experiments.trial_models import (
    FactorTrial,
    TrialBatch,
    TrialBatchDescriptor,
)

__all__ = [
    "FactorTrial",
    "TrialBatch",
    "TrialBatchDescriptor",
    "TrialLedgerError",
    "TrialLedgerStore",
    "TrialRegistrationContext",
    "create_trial_batch",
]


class TrialLedgerStore:
    """Publish complete trial batches atomically and verify them before use."""

    def __init__(self, root: Path) -> None:
        """Bind the ledger to a caller-owned local artifact root."""
        self._root = root / "trial_ledger"

    def write(self, batch: TrialBatch) -> TrialBatchDescriptor:
        """Append one batch or verify an identical existing registration."""
        _validate(batch)
        content = f"{batch.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        directory = self._root / batch.batch_id
        descriptor = TrialBatchDescriptor(
            batch_id=batch.batch_id,
            manifest_path=directory / "manifest.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != batch:
                detail = "existing trial batch content differs"
                raise TrialLedgerError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "manifest.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: TrialBatchDescriptor) -> TrialBatch:
        """Verify exact path, schema, bytes, and declared batch identity."""
        expected = self._root / descriptor.batch_id / "manifest.json"
        if descriptor.manifest_path != expected:
            detail = "descriptor crosses trial ledger boundary"
            raise TrialLedgerError(detail)
        try:
            content = descriptor.manifest_path.read_bytes()
            batch = TrialBatch.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "trial batch manifest is missing or invalid"
            raise TrialLedgerError(detail) from error
        _validate(batch)
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or batch.batch_id != descriptor.batch_id:
            detail = "trial batch bytes differ from descriptor"
            raise TrialLedgerError(detail)
        return batch


class TrialLedgerError(Exception):
    """Trial registration is incomplete, altered, or crosses its ledger boundary."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed trial ledger failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable ledger boundary and concrete failure."""
        return f"trial_ledger: {self.detail}"


def _validate(batch: TrialBatch) -> None:
    try:
        validate_trial_identities(batch)
    except TrialIdentityError as error:
        raise TrialLedgerError(error.detail) from error
