"""Content-addressed immutable Tushare Raw snapshots."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from ashare_lab.data.schema_registry import EndpointSchema, SchemaContractError
from ashare_lab.data.tushare_client import Scalar, TushareQuery, TushareTable

_INDEX_BASIC_PROVIDER_ROW_CAP: Final = 8_000


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Audit manifest for one exact provider response."""

    snapshot_id: str
    source: str
    endpoint: str
    request_params_canonical: str
    requested_at: datetime
    completed_at: datetime
    provider_version: str | None
    row_count: int
    payload_sha256: str
    schema_manifest_id: str
    status: str


@dataclass(frozen=True, slots=True)
class RawRow:
    """One immutable provider row bound to its source snapshot."""

    snapshot_id: str
    row_ordinal: int
    ingested_at: datetime
    row_sha256: str
    payload: tuple[tuple[str, Scalar], ...]


@dataclass(frozen=True, slots=True)
class SnapshotBatch:
    """Snapshot manifest and all Raw rows written atomically by the store."""

    snapshot: SourceSnapshot
    rows: tuple[RawRow, ...]


@dataclass(frozen=True, slots=True)
class SnapshotTiming:
    """Provider request interval used by one snapshot."""

    requested_at: datetime
    completed_at: datetime


def build_raw_snapshot(
    query: TushareQuery,
    table: TushareTable,
    endpoint_schema: EndpointSchema,
    schema_manifest_id: str,
    timing: SnapshotTiming,
) -> SnapshotBatch:
    """Validate the field contract and build deterministic snapshot identities."""
    if query.endpoint == "" or table.fields != endpoint_schema.field_names:
        detail = (
            f"{query.endpoint} response fields do not match committed field contract: "
            f"expected={endpoint_schema.field_names} actual={table.fields}"
        )
        raise SchemaContractError(detail)
    if query.fields != endpoint_schema.field_names:
        detail = f"{query.endpoint} request does not match committed field contract"
        raise SchemaContractError(detail)
    if any(len(row.values) != len(table.fields) for row in table.rows):
        detail = f"{query.endpoint} response row width violates field contract"
        raise SchemaContractError(detail)
    if (
        query.endpoint == "index_basic"
        and len(table.rows) >= _INDEX_BASIC_PROVIDER_ROW_CAP
        and all(param.name != "ts_code" for param in query.params)
    ):
        detail = "index_basic broad response reached provider row cap"
        raise SchemaContractError(detail)

    params = json.dumps(
        {item.name: item.value for item in query.params},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    response_payload = json.dumps(
        {"fields": table.fields, "items": tuple(row.values for row in table.rows)},
        ensure_ascii=True,
        separators=(",", ":"),
    )
    payload_sha256 = hashlib.sha256(response_payload.encode()).hexdigest()
    identity = f"tushare|{query.endpoint}|{params}|{payload_sha256}|{schema_manifest_id}"
    snapshot_id = f"snap_{hashlib.sha256(identity.encode()).hexdigest()}"
    rows = tuple(
        _build_row(snapshot_id, ordinal, table.fields, row.values, timing.completed_at)
        for ordinal, row in enumerate(table.rows)
    )
    snapshot = SourceSnapshot(
        snapshot_id=snapshot_id,
        source="tushare",
        endpoint=query.endpoint,
        request_params_canonical=params,
        requested_at=timing.requested_at,
        completed_at=timing.completed_at,
        provider_version=None,
        row_count=len(rows),
        payload_sha256=payload_sha256,
        schema_manifest_id=schema_manifest_id,
        status="RECEIVED",
    )
    return SnapshotBatch(snapshot=snapshot, rows=rows)


def _build_row(
    snapshot_id: str,
    ordinal: int,
    fields: tuple[str, ...],
    values: tuple[Scalar, ...],
    ingested_at: datetime,
) -> RawRow:
    payload = tuple(zip(fields, values, strict=True))
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return RawRow(
        snapshot_id=snapshot_id,
        row_ordinal=ordinal,
        ingested_at=ingested_at,
        row_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        payload=payload,
    )
