from datetime import UTC, datetime

import pytest

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.research.datasets.evidence import (
    ArtifactEvidence,
    LineageEvidence,
    QualityEvidence,
    SnapshotEvidence,
    audit_artifact_evidence,
)
from ashare_lab.research.datasets.mongo_evidence import (
    DatasetEvidenceReaderError,
    EvidenceCollection,
    MongoDatasetEvidenceReader,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)


class _Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self._documents = documents

    def find(
        self,
        _query: BsonDocument,
        _projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        return self._documents


class _Database:
    def __init__(self, name: str, documents: dict[str, tuple[BsonDocument, ...]]) -> None:
        self.name = name
        self._documents = documents

    def __getitem__(self, collection: str) -> _Collection:
        return _Collection(self._documents[collection])


def _artifact() -> ArtifactEvidence:
    return ArtifactEvidence(
        artifact_id="event_001",
        source_snapshot_id="snap_001",
        input_schema_manifest_id="schema_abc",
        schema_manifest_id="schema_abc",
        quality_report_id="quality_001",
        quality_status="ACCEPTED",
        available_at=NOW,
    )


def _snapshot(status: str = "ACCEPTED") -> SnapshotEvidence:
    return SnapshotEvidence("snap_001", "schema_abc", status)


def _quality(*, passed: bool = True) -> QualityEvidence:
    return QualityEvidence("quality_001", "event_001", passed)


def _lineage(code_commit: str = "a" * 40) -> LineageEvidence:
    return LineageEvidence(
        lineage_edge_id="lineage_001",
        upstream_artifact_id="snap_001",
        downstream_artifact_id="event_001",
        output_schema_id="schema_abc",
        code_commit=code_commit,
    )


def test_evidence_audit_accepts_a_complete_versioned_chain() -> None:
    # Given: one PIT artifact with accepted Raw, quality, lineage, and Git evidence.
    # When: the chain is audited.
    result = audit_artifact_evidence(
        (_artifact(),),
        (_snapshot(),),
        (_quality(),),
        (_lineage(),),
    )

    # Then: exact source and lineage identities are eligible for dataset coverage.
    assert result.blockers == ()
    assert result.quality_passed is True
    assert result.point_in_time is True
    assert result.source_snapshot_ids == ("snap_001",)
    assert result.lineage_edge_ids == ("lineage_001",)


def test_evidence_audit_blocks_workspace_unversioned_lineage() -> None:
    # Given: the historical pre-Git lineage marker.
    # When: the artifact chain is audited.
    result = audit_artifact_evidence(
        (_artifact(),),
        (_snapshot(),),
        (_quality(),),
        (_lineage("workspace_unversioned"),),
    )

    # Then: the old artifact stays auditable but cannot qualify for training.
    assert result.blockers == ("unversioned_lineage",)
    assert result.lineage_edge_ids == ()


def test_evidence_audit_accepts_cross_schema_pit_projection() -> None:
    # Given: a market Raw row conservatively projected into the universe schema.
    artifact = ArtifactEvidence(
        artifact_id="event_001",
        source_snapshot_id="snap_001",
        input_schema_manifest_id="schema_market",
        schema_manifest_id="schema_universe",
        quality_report_id="quality_001",
        quality_status="ACCEPTED",
        available_at=NOW,
    )
    snapshot = SnapshotEvidence("snap_001", "schema_market", "ACCEPTED")
    lineage = LineageEvidence(
        "lineage_001",
        "snap_001",
        "event_001",
        "schema_universe",
        "a" * 40,
    )

    # When: input and output schemas are checked in their separate roles.
    result = audit_artifact_evidence((artifact,), (snapshot,), (_quality(),), (lineage,))

    # Then: the legitimate cross-schema projection remains eligible.
    assert result.blockers == ()


def test_evidence_audit_blocks_missing_quality_and_raw_snapshot() -> None:
    # Given: a PIT row without its claimed Raw or quality evidence.
    # When: the incomplete chain is audited.
    result = audit_artifact_evidence((_artifact(),), (), (), (_lineage(),))

    # Then: both independent gaps are reported without an all-empty pass.
    assert result.blockers == ("missing_quality", "missing_raw_snapshot")
    assert result.quality_passed is False


def test_evidence_audit_blocks_quarantined_artifacts() -> None:
    # Given: a row that carries evidence but is not accepted for research.
    artifact = ArtifactEvidence(
        artifact_id="event_001",
        source_snapshot_id="snap_001",
        input_schema_manifest_id="schema_abc",
        schema_manifest_id="schema_abc",
        quality_report_id="quality_001",
        quality_status="QUARANTINED",
        available_at=NOW,
    )

    # When: its chain is audited.
    result = audit_artifact_evidence(
        (artifact,),
        (_snapshot(),),
        (_quality(),),
        (_lineage(),),
    )

    # Then: quarantine cannot be bypassed by otherwise complete metadata.
    assert result.blockers == ("artifact_not_accepted",)
    assert result.quality_passed is False


def test_mongo_reader_parses_a_complete_cross_schema_chain() -> None:
    # Given: Mongo-shaped documents for a conservative first-traded event.
    database = _Database(
        "ashare_quant",
        {
            "pit_security_events": (
                {
                    "_id": "event_001",
                    "source_snapshot_id": "snap_001",
                    "input_schema_manifest_id": "schema_market",
                    "schema_manifest_id": "schema_universe",
                    "quality_report_id": "quality_001",
                    "quality_status": "ACCEPTED",
                    "available_at": NOW.replace(tzinfo=None),
                },
            ),
            "meta_source_snapshots": (
                {
                    "snapshot_id": "snap_001",
                    "schema_manifest_id": "schema_market",
                    "status": "ACCEPTED",
                },
            ),
            "meta_quality_reports": (
                {
                    "quality_report_id": "quality_001",
                    "artifact_id": "event_001",
                    "passed": True,
                },
            ),
            "meta_lineage_edges": (
                {
                    "lineage_edge_id": "lineage_001",
                    "upstream_artifact_id": "snap_001",
                    "downstream_artifact_id": "event_001",
                    "output_schema_id": "schema_universe",
                    "code_commit": "a" * 40,
                },
            ),
        },
    )

    # When: the real Mongo adapter audits the collection boundary.
    result = MongoDatasetEvidenceReader(database).audit_collection(
        EvidenceCollection.UNIVERSE,
        "schema_universe",
    )

    # Then: BSON is normalized into a complete PIT evidence chain.
    assert result.blockers == ()
    assert result.point_in_time is True


def test_mongo_reader_rejects_an_unowned_database() -> None:
    # Given: a database outside the governed isolation boundary.
    database = _Database("legacy", {})

    # When / Then: the adapter refuses to bind before any collection read.
    with pytest.raises(DatasetEvidenceReaderError, match="ashare_quant"):
        MongoDatasetEvidenceReader(database)
