from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import CanonicalBatch, canonicalize_batch
from ashare_lab.data.canonical_store import CanonicalWriteResult
from ashare_lab.data.cli import app
from ashare_lab.data.financial_indicator_store import IndicatorWriteResult
from ashare_lab.data.financial_indicators import FinancialIndicatorVersion
from ashare_lab.data.industry_memberships import IndustryMembership
from ashare_lab.data.industry_store import IndustryWriteResult
from ashare_lab.data.raw_replay import build_stored_snapshot_batch
from ashare_lab.data.rematerialization import (
    ProjectionResult,
    RematerializationJob,
    RematerializationResult,
    rematerialize_batches,
)
from ashare_lab.data.rematerialization_checkpoint import MongoRematerializationCheckpoint
from ashare_lab.data.rematerialization_projectors import (
    CanonicalOnlyProjector,
    FinancialIndicatorProjector,
    IndustryProjector,
    UniverseProjector,
    first_trade_lineage_events,
)
from ashare_lab.data.rematerialization_runtime import (
    RematerializationTarget,
    target_contract,
)
from ashare_lab.data.schema_registry import EndpointSchema, SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotBatch
from ashare_lab.data.universe import SecurityEvent, SecurityEventType
from ashare_lab.data.universe_builder import build_first_trade_event
from ashare_lab.data.universe_store import UniverseEventWriteResult
from tests.test_raw_replay import (
    replay_registry,
    replay_row,
    replay_schema,
    replay_snapshot,
)


class _Reader:
    def __init__(self, snapshot_ids: tuple[str, ...] = ("snap_001",)) -> None:
        self._snapshot_ids = snapshot_ids

    def accepted_snapshot_ids(
        self,
        registry: SchemaRegistry,
        endpoints: tuple[str, ...],
    ) -> tuple[str, ...]:
        del registry, endpoints
        return self._snapshot_ids

    def load_batch(
        self,
        registry: SchemaRegistry,
        snapshot_id: str,
    ) -> SnapshotBatch:
        del registry
        return build_stored_snapshot_batch(
            replay_snapshot(snapshot_id=snapshot_id),
            (replay_row(snapshot_id=snapshot_id),),
            replay_schema(),
        )


class _CanonicalSink:
    def __init__(self) -> None:
        self.artifact_ids: list[str] = []

    def write_replayed(
        self,
        schema: EndpointSchema,
        batch: CanonicalBatch,
    ) -> CanonicalWriteResult:
        del schema
        self.artifact_ids.append(batch.artifact_id)
        return CanonicalWriteResult(batch.artifact_id, len(batch.records), 0, "ACCEPTED")


class _Projector:
    def __init__(self) -> None:
        self.batch_count = 0

    def project(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        del batch
        self.batch_count += 1
        return ProjectionResult(event_count=len(canonical.records), inserted_count=0)


class _FailingProjector:
    @staticmethod
    def project(batch: SnapshotBatch, canonical: CanonicalBatch) -> ProjectionResult:
        del batch, canonical
        detail = "owned PIT projection failed"
        raise SchemaContractError(detail)


class _Checkpoint:
    def __init__(self, completed: set[str] | None = None) -> None:
        self.completed = completed if completed is not None else set()
        self.recorded: list[str] = []

    def is_complete(self, snapshot_id: str, schema_manifest_id: str) -> bool:
        del schema_manifest_id
        return snapshot_id in self.completed

    def complete(self, batch: SnapshotBatch, canonical: CanonicalBatch) -> None:
        del canonical
        self.completed.add(batch.snapshot.snapshot_id)
        self.recorded.append(batch.snapshot.snapshot_id)


class _StoredCheckpointCollection:
    def __init__(self) -> None:
        self.last_query: dict[str, str] = {}
        self.last_update: BsonDocument = {}

    def find_one(
        self,
        query: dict[str, str],
        _projection: dict[str, int],
    ) -> dict[str, str]:
        self.last_query = query
        return {"_id": "lineage_from_prior_non_material_commit"}

    def update_one(
        self,
        _query: BsonDocument,
        update: BsonDocument,
        *,
        upsert: bool,
    ) -> None:
        assert upsert is True
        self.last_update = update


class _StoredCheckpointDatabase:
    def __init__(self) -> None:
        self.collection = _StoredCheckpointCollection()

    def __getitem__(self, _name: str) -> _StoredCheckpointCollection:
        return self.collection


class _UniverseStore:
    @staticmethod
    def write(events: tuple[SecurityEvent, ...]) -> UniverseEventWriteResult:
        return UniverseEventWriteResult(len(events), 0)


class _FinancialIndicatorStore:
    @staticmethod
    def write_batch(
        canonical: CanonicalBatch,
        events: tuple[FinancialIndicatorVersion, ...],
    ) -> IndicatorWriteResult:
        return IndicatorWriteResult(canonical.artifact_id, len(events), 0)


class _IndustryStore:
    @staticmethod
    def write_batch(
        canonical: CanonicalBatch,
        events: tuple[IndustryMembership, ...],
    ) -> IndustryWriteResult:
        return IndustryWriteResult(canonical.artifact_id, len(events), 0)


def _daily_batch() -> tuple[SnapshotBatch, CanonicalBatch]:
    batch = build_stored_snapshot_batch(
        replay_snapshot(),
        (replay_row(),),
        replay_schema(),
    )
    return batch, canonicalize_batch(
        batch,
        replay_schema(),
        replay_registry().manifest_id,
    )


def test_rematerialization_replays_raw_through_canonical_and_pit_projection() -> None:
    # Given: one accepted Raw batch and recording transformation boundaries.
    sink = _CanonicalSink()
    projector = _Projector()
    checkpoint = _Checkpoint()

    # When: the model-independent rematerialization orchestration executes.
    result = rematerialize_batches(
        RematerializationJob(
            replay_registry(),
            ("daily",),
            _Reader(),
            sink,
            projector,
            checkpoint,
        ),
        max_batches=10,
    )

    # Then: one deterministic canonical artifact and one projection are audited.
    assert result == RematerializationResult(
        batch_count=1,
        record_count=1,
        canonical_inserted_count=0,
        event_count=1,
        event_inserted_count=0,
        skipped_completed_count=0,
        has_more=False,
    )
    assert len(sink.artifact_ids) == 1
    assert projector.batch_count == 1
    assert checkpoint.recorded == ["snap_001"]


def test_rematerialization_skips_only_batches_with_final_completion_evidence() -> None:
    # Given: one completed batch followed by one batch with no final replay evidence.
    checkpoint = _Checkpoint({"snap_001"})

    # When: a bounded replay evaluates both immutable Raw identities.
    result = rematerialize_batches(
        RematerializationJob(
            replay_registry(),
            ("daily",),
            _Reader(("snap_001", "snap_002")),
            _CanonicalSink(),
            _Projector(),
            checkpoint,
        ),
        max_batches=10,
    )

    # Then: only the incomplete batch crosses canonical and projection boundaries.
    assert result.batch_count == 1
    assert result.skipped_completed_count == 1
    assert checkpoint.recorded == ["snap_002"]


def test_rematerialization_stops_at_a_bounded_number_of_incomplete_batches() -> None:
    # Given: two incomplete accepted Raw batches and a one-batch process budget.
    checkpoint = _Checkpoint()

    # When: replay reaches its explicit batch bound.
    result = rematerialize_batches(
        RematerializationJob(
            replay_registry(),
            ("daily",),
            _Reader(("snap_001", "snap_002")),
            _CanonicalSink(),
            _Projector(),
            checkpoint,
        ),
        max_batches=1,
    )

    # Then: one batch is durably complete and the result signals more work.
    assert result.batch_count == 1
    assert result.has_more is True
    assert checkpoint.recorded == ["snap_001"]


def test_rematerialization_does_not_mark_completion_when_projection_fails() -> None:
    # Given: an accepted Raw batch whose owned PIT projection will fail closed.
    checkpoint = _Checkpoint()
    job = RematerializationJob(
        replay_registry(),
        ("daily",),
        _Reader(),
        _CanonicalSink(),
        _FailingProjector(),
        checkpoint,
    )

    # When / Then: the projection error propagates without final completion evidence.
    with pytest.raises(SchemaContractError, match="owned PIT projection failed"):
        rematerialize_batches(job, max_batches=1)
    assert checkpoint.recorded == []


def test_checkpoint_reuses_same_version_completion_across_code_commits() -> None:
    # Given: completion evidence from the same material transform version and schema.
    database = _StoredCheckpointDatabase()
    checkpoint = MongoRematerializationCheckpoint.__new__(MongoRematerializationCheckpoint)
    checkpoint.__dict__["_database"] = database
    checkpoint.__dict__["_code_commit"] = "new_commit"

    # When: current replay checks whether the stored Raw batch is complete.
    completed = checkpoint.is_complete("snap_001", "schema_abc")

    # Then: code identity remains audited but is not a non-material replay cursor.
    assert completed is True
    assert "code_commit" not in database.collection.last_query


def test_checkpoint_writes_content_addressed_versioned_completion_lineage() -> None:
    # Given: one fully projected Raw and canonical batch under a real code identity.
    batch, canonical = _daily_batch()
    database = _StoredCheckpointDatabase()
    checkpoint = MongoRematerializationCheckpoint.__new__(MongoRematerializationCheckpoint)
    checkpoint.__dict__["_database"] = database
    checkpoint.__dict__["_code_commit"] = "a" * 40

    # When: replay records final completion after all owned stages succeed.
    checkpoint.complete(batch, canonical)

    # Then: the append-only edge pins code, schema, and material transform version.
    inserted = database.collection.last_update["$setOnInsert"]
    assert isinstance(inserted, dict)
    assert inserted["code_commit"] == "a" * 40
    assert inserted["output_schema_id"] == canonical.schema_manifest_id
    assert inserted["transform_version"] == "1.0.0"


def test_canonical_only_projector_records_an_explicit_zero_event_projection() -> None:
    # Given: one canonicalized Raw batch that requires no PIT event projection.
    batch, canonical = _daily_batch()

    # When: the canonical-only projection boundary is executed.
    result = CanonicalOnlyProjector().project(batch, canonical)

    # Then: the completed no-op remains visible in aggregate replay evidence.
    assert result == ProjectionResult(event_count=0, inserted_count=0)


@pytest.mark.parametrize(
    "projector",
    [
        UniverseProjector(_UniverseStore()),
        FinancialIndicatorProjector(_FinancialIndicatorStore()),
        IndustryProjector(_IndustryStore()),
    ],
)
def test_pit_projectors_reject_raw_endpoints_outside_their_owned_contract(
    projector: UniverseProjector | FinancialIndicatorProjector | IndustryProjector,
) -> None:
    # Given: a valid daily market batch presented to a specialized PIT projector.
    batch, canonical = _daily_batch()

    # When / Then: the projector fails closed instead of creating foreign events.
    with pytest.raises(SchemaContractError, match="unsupported"):
        projector.project(batch, canonical)


def test_universe_fallback_lineage_selects_only_daily_first_trade_events() -> None:
    # Given: one conservative daily fallback and one ordinary listed event.
    _, canonical = _daily_batch()
    fallback = build_first_trade_event(canonical.records[0], "schema_universe")
    listed = replace(
        fallback,
        event_id="listed",
        event_type=SecurityEventType.LISTED,
        source_endpoint="stock_basic",
    )

    # When: replay selects historical fallback events needing their owned lineage path.
    selected = first_trade_lineage_events((fallback, listed))

    # Then: no other lifecycle variant is written through the fallback path.
    assert selected == (fallback,)


@pytest.mark.parametrize(
    ("target", "schema_path", "endpoints"),
    [
        (
            RematerializationTarget.MARKET,
            Path("schemas/tushare_p0_v1.json"),
            ("trade_cal", "daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d"),
        ),
        (
            RematerializationTarget.BENCHMARK_DAILY,
            Path("schemas/tushare_benchmarks_v1.json"),
            ("index_daily",),
        ),
        (
            RematerializationTarget.UNIVERSE,
            Path("schemas/tushare_universe_v1.json"),
            ("stock_basic", "namechange"),
        ),
        (
            RematerializationTarget.FINANCIAL_INDICATORS,
            Path("schemas/tushare_financial_indicator_v1.json"),
            ("fina_indicator",),
        ),
        (
            RematerializationTarget.INDUSTRY,
            Path("schemas/tushare_industry_v1.json"),
            ("index_member",),
        ),
    ],
)
def test_rematerialization_targets_bind_one_committed_schema_and_endpoint_set(
    target: RematerializationTarget,
    schema_path: Path,
    endpoints: tuple[str, ...],
) -> None:
    # Given: one closed operator target and its committed schema contract.
    expected_manifest = SchemaRegistry.load(schema_path).manifest_id

    # When: the runtime resolves its replay contract.
    registry, resolved_endpoints = target_contract(target)

    # Then: neither the schema identity nor source endpoints can drift dynamically.
    assert registry.manifest_id == expected_manifest
    assert resolved_endpoints == endpoints


def test_data_cli_registers_the_governed_rematerialization_command() -> None:
    # Given: the production data CLI composition root.
    runner = CliRunner()

    # When: an operator asks for command help without opening MongoDB.
    result = runner.invoke(app, ["rematerialize-lineage", "--help"])

    # Then: the offline target argument is exposed through the governed entry point.
    assert result.exit_code == 0
    assert "market" in result.stdout
    assert "financial_indicators" in result.stdout
