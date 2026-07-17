"""Strict reconstruction of accepted SnapshotBatch values from immutable Mongo Raw."""

from datetime import UTC, datetime
from enum import StrEnum, unique
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.schema_registry import EndpointSchema
from ashare_lab.data.snapshots import RawRow, SnapshotBatch, SourceSnapshot
from ashare_lab.data.tushare_client import Scalar

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@unique
class RawReplayRule(StrEnum):
    """Stable failure codes for immutable Raw reconstruction."""

    DATABASE_ISOLATION = "database_isolation"
    SNAPSHOT_MISSING = "snapshot_missing"
    SNAPSHOT_NOT_ACCEPTED = "snapshot_not_accepted"
    ROW_COUNT_MISMATCH = "row_count_mismatch"
    ROW_ORDER_MISMATCH = "row_order_mismatch"
    ROW_SNAPSHOT_MISMATCH = "row_snapshot_mismatch"
    FIELD_CONTRACT_MISMATCH = "field_contract_mismatch"


class RawReplayError(Exception):
    """Stored Raw cannot safely cross the canonical transformation boundary."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: RawReplayRule, detail: str) -> None:
        """Create a typed replay rejection."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable rule and concrete mismatch."""
        return f"{self.rule.value}: {self.detail}"


class _SnapshotDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    source: str
    endpoint: str
    request_params_canonical: str
    requested_at: datetime
    completed_at: datetime
    provider_version: str | None
    row_count: int = Field(ge=0)
    payload_sha256: str
    schema_manifest_id: str
    status: str


class _RawDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    snapshot_id: str
    row_ordinal: int = Field(ge=0)
    ingested_at: datetime
    row_sha256: str
    payload: dict[str, Scalar]


def build_stored_snapshot_batch(
    snapshot_document: BsonDocument,
    raw_documents: tuple[BsonDocument, ...],
    schema: EndpointSchema,
) -> SnapshotBatch:
    """Parse and validate stored Raw before deterministic transformation replay."""
    snapshot = _SnapshotDocument.model_validate(snapshot_document)
    if snapshot.status != "ACCEPTED":
        raise RawReplayError(
            RawReplayRule.SNAPSHOT_NOT_ACCEPTED,
            f"snapshot {snapshot.snapshot_id} has status {snapshot.status}",
        )
    rows = tuple(sorted((_RawDocument.model_validate(row) for row in raw_documents), key=_ordinal))
    if len(rows) != snapshot.row_count:
        raise RawReplayError(
            RawReplayRule.ROW_COUNT_MISMATCH,
            f"expected {snapshot.row_count} rows, found {len(rows)}",
        )
    if tuple(row.row_ordinal for row in rows) != tuple(range(len(rows))):
        raise RawReplayError(
            RawReplayRule.ROW_ORDER_MISMATCH,
            "Raw row ordinals must be contiguous and zero-based",
        )
    if any(row.snapshot_id != snapshot.snapshot_id for row in rows):
        raise RawReplayError(
            RawReplayRule.ROW_SNAPSHOT_MISMATCH,
            "Raw row references another snapshot",
        )
    expected_fields = schema.field_names
    if any(set(row.payload) != set(expected_fields) for row in rows):
        raise RawReplayError(
            RawReplayRule.FIELD_CONTRACT_MISMATCH,
            "Raw payload fields differ from the committed endpoint schema",
        )
    return SnapshotBatch(
        snapshot=_source_snapshot(snapshot),
        rows=tuple(_raw_row(row, expected_fields) for row in rows),
    )


def _source_snapshot(document: _SnapshotDocument) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot_id=document.snapshot_id,
        source=document.source,
        endpoint=document.endpoint,
        request_params_canonical=document.request_params_canonical,
        requested_at=_restore_mongo_time(document.requested_at),
        completed_at=_restore_mongo_time(document.completed_at),
        provider_version=document.provider_version,
        row_count=document.row_count,
        payload_sha256=document.payload_sha256,
        schema_manifest_id=document.schema_manifest_id,
        status=document.status,
    )


def _raw_row(document: _RawDocument, fields: tuple[str, ...]) -> RawRow:
    return RawRow(
        snapshot_id=document.snapshot_id,
        row_ordinal=document.row_ordinal,
        ingested_at=_restore_mongo_time(document.ingested_at),
        row_sha256=document.row_sha256,
        payload=tuple((field, document.payload[field]) for field in fields),
    )


def _ordinal(document: _RawDocument) -> int:
    return document.row_ordinal


def _restore_mongo_time(value: datetime) -> datetime:
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.astimezone(_SHANGHAI)
