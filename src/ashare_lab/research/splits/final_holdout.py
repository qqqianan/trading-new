"""Sealed final-holdout boundary with a single-use append-only access ledger."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class FrozenHoldoutModel(BaseModel):
    """Immutable boundary model used in holdout manifests and ledger records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FinalHoldoutSpec(FrozenHoldoutModel):
    """Dataset-bound date boundary that is frozen before development begins."""

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    development_end: date
    holdout_start: date
    protocol_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")

    @model_validator(mode="after")
    def partitions_do_not_overlap(self) -> Self:
        """Reject a final partition that intersects development."""
        if self.holdout_start <= self.development_end:
            detail = "holdout_start must be after development_end"
            raise ValueError(detail)
        return self

    @property
    def spec_id(self) -> str:
        """Return a content identity for the complete boundary contract."""
        return _model_id("holdout_spec", self)


class FrozenResearchProtocol(FrozenHoldoutModel):
    """Immutable proof that method choices were fixed before final evaluation."""

    holdout_spec_id: str = Field(pattern=r"^holdout_spec_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    split_protocol_id: str = Field(min_length=1)
    preprocessing_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    frozen_at: datetime
    frozen_by: str = Field(min_length=1)

    @property
    def protocol_id(self) -> str:
        """Return the frozen method identity required by an opening authorization."""
        return _model_id("protocol", self)


class FinalHoldoutAccessRequest(FrozenHoldoutModel):
    """Explicit one-time authorization bound to one already-frozen protocol."""

    protocol_id: str = Field(pattern=r"^protocol_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    authorized_at: datetime
    authorized_by: str = Field(min_length=1)
    purpose: str = Field(pattern=r"^single_final_evaluation$")


class HoldoutAccessRecord(FrozenHoldoutModel):
    """Append-only evidence that the final holdout was exposed once."""

    record_id: str = Field(pattern=r"^holdout_access_[0-9a-f]{64}$")
    holdout_spec_id: str = Field(pattern=r"^holdout_spec_[0-9a-f]{64}$")
    protocol_id: str = Field(pattern=r"^protocol_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    accessed_at: datetime
    authorized_by: str
    purpose: str


class FinalHoldoutError(Exception):
    """A caller attempted an unauthorized or repeated final-holdout read."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed holdout rejection."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the holdout boundary and concrete failure."""
        return f"final_holdout: {self.detail}"


class DevelopmentDatasetReader:
    """Expose only observations on or before the frozen development cutoff."""

    def __init__(self, spec: FinalHoldoutSpec) -> None:
        """Bind the default reader to one immutable holdout contract."""
        self._spec = spec

    def read(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Physically remove sealed rows from the default research surface."""
        return frame.filter(pl.col("decision_time").dt.date() <= pl.lit(self._spec.development_end))

    def read_through(self, frame: pl.DataFrame, requested_end: date) -> pl.DataFrame:
        """Reject an explicit request crossing into the final holdout."""
        if requested_end > self._spec.development_end:
            detail = "requested date is sealed"
            raise FinalHoldoutError(detail)
        return self.read(frame).filter(pl.col("decision_time").dt.date() <= pl.lit(requested_end))


class FinalHoldoutAccessLedger:
    """Use exclusive file creation as a cross-process single-access claim."""

    def __init__(self, root: Path) -> None:
        """Bind ledger records to one caller-owned local root."""
        self._root = root / "final_holdout_access"

    def append_once(self, record: HoldoutAccessRecord) -> None:
        """Atomically append the only permitted record for one holdout spec."""
        directory = self._root / record.holdout_spec_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "000001.json"
        try:
            with path.open("x", encoding="utf-8") as output:
                output.write(record.model_dump_json(indent=2))
                output.write("\n")
        except FileExistsError as error:
            detail = "final holdout was already opened"
            raise FinalHoldoutError(detail) from error

    def count(self, holdout_spec_id: str) -> int:
        """Count valid immutable records, failing closed on malformed evidence."""
        directory = self._root / holdout_spec_id
        if not directory.exists():
            return 0
        paths = tuple(sorted(directory.glob("*.json")))
        try:
            for path in paths:
                HoldoutAccessRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as error:
            detail = "access ledger is invalid"
            raise FinalHoldoutError(detail) from error
        return len(paths)


class FinalHoldoutGate:
    """Validate frozen authorization, claim the ledger, then expose holdout rows."""

    def __init__(
        self,
        spec: FinalHoldoutSpec,
        protocol: FrozenResearchProtocol,
        ledger: FinalHoldoutAccessLedger,
    ) -> None:
        """Bind one sealed partition, frozen protocol, and durable ledger."""
        self._spec = spec
        self._protocol = protocol
        self._ledger = ledger

    def open_once(
        self,
        frame: pl.DataFrame,
        request: FinalHoldoutAccessRequest,
    ) -> pl.DataFrame:
        """Expose the final partition only after an atomic one-time claim."""
        if (
            self._protocol.holdout_spec_id != self._spec.spec_id
            or self._protocol.dataset_snapshot_id != self._spec.dataset_snapshot_id
            or request.protocol_id != self._protocol.protocol_id
            or request.dataset_snapshot_id != self._spec.dataset_snapshot_id
        ):
            detail = "authorization does not match the frozen protocol"
            raise FinalHoldoutError(detail)
        if request.authorized_at <= self._protocol.frozen_at:
            detail = "authorization must be issued after protocol freeze"
            raise FinalHoldoutError(detail)
        record_payload = (
            f"{self._spec.spec_id}|{request.protocol_id}|{request.dataset_snapshot_id}|"
            f"{request.authorized_at.isoformat()}|{request.authorized_by}|{request.purpose}"
        )
        record = HoldoutAccessRecord(
            record_id=f"holdout_access_{hashlib.sha256(record_payload.encode()).hexdigest()}",
            holdout_spec_id=self._spec.spec_id,
            protocol_id=request.protocol_id,
            dataset_snapshot_id=request.dataset_snapshot_id,
            accessed_at=request.authorized_at,
            authorized_by=request.authorized_by,
            purpose=request.purpose,
        )
        self._ledger.append_once(record)
        return frame.filter(pl.col("decision_time").dt.date() >= pl.lit(self._spec.holdout_start))


def _model_id(prefix: str, model: FrozenHoldoutModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()}"
