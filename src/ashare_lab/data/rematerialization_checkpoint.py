"""Append-only final completion evidence for resumable Raw rematerialization."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ashare_lab.code_identity import load_git_commit

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.database import Database

    from ashare_lab.data.bson_types import BsonDocument
    from ashare_lab.data.canonical import CanonicalBatch
    from ashare_lab.data.snapshots import SnapshotBatch

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRANSFORM_NAME = "governed_raw_rematerialization_complete"
_TRANSFORM_VERSION = "1.0.0"


class MongoRematerializationCheckpoint:
    """Record completion only after canonical and PIT writes both succeed."""

    def __init__(self, client: MongoClient[BsonDocument], database_name: str) -> None:
        """Bind completion evidence to one code identity and governed database."""
        if database_name != "ashare_quant":
            msg = "rematerialization checkpoint is restricted to ashare_quant"
            raise ValueError(msg)
        self._database: Database[BsonDocument] = client[database_name]
        self._code_commit = load_git_commit(Path.cwd())

    def is_complete(self, snapshot_id: str, schema_manifest_id: str) -> bool:
        """Check the indexed Raw/schema pair for this material transform version."""
        evidence = self._database["meta_lineage_edges"].find_one(
            {
                "upstream_artifact_id": snapshot_id,
                "output_schema_id": schema_manifest_id,
                "transform_name": _TRANSFORM_NAME,
                "transform_version": _TRANSFORM_VERSION,
            },
            {"_id": 1},
        )
        return evidence is not None

    def complete(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> None:
        """Append a stable edge proving all owned replay stages completed."""
        identity = (
            f"{batch.snapshot.snapshot_id}|{canonical.schema_manifest_id}|"
            f"{self._code_commit}|{_TRANSFORM_VERSION}"
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()
        edge_id = f"lineage_{digest}"
        artifact_id = f"rematerialization_completion_{digest}"
        self._database["meta_lineage_edges"].update_one(
            {"_id": edge_id},
            {
                "$setOnInsert": {
                    "_id": edge_id,
                    "lineage_edge_id": edge_id,
                    "upstream_artifact_id": batch.snapshot.snapshot_id,
                    "downstream_artifact_id": artifact_id,
                    "transform_name": _TRANSFORM_NAME,
                    "transform_version": _TRANSFORM_VERSION,
                    "code_commit": self._code_commit,
                    "input_schema_ids": [canonical.schema_manifest_id],
                    "output_schema_id": canonical.schema_manifest_id,
                    "parameters_sha256": hashlib.sha256(
                        batch.snapshot.endpoint.encode()
                    ).hexdigest(),
                    "field_mappings": ["completion<-canonical_and_owned_pit_projection"],
                    "executed_at": datetime.now(_SHANGHAI),
                }
            },
            upsert=True,
        )
