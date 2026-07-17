from pathlib import Path

import pytest
from typer.testing import CliRunner

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
    RematerializationResult,
    rematerialize_batches,
)
from ashare_lab.data.rematerialization_projectors import (
    CanonicalOnlyProjector,
    FinancialIndicatorProjector,
    IndustryProjector,
    UniverseProjector,
)
from ashare_lab.data.rematerialization_runtime import (
    RematerializationTarget,
    target_contract,
)
from ashare_lab.data.schema_registry import EndpointSchema, SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotBatch
from ashare_lab.data.universe import SecurityEvent
from ashare_lab.data.universe_store import UniverseEventWriteResult
from tests.test_raw_replay import (
    replay_registry,
    replay_row,
    replay_schema,
    replay_snapshot,
)


class _Reader:
    def accepted_snapshot_ids(
        self,
        registry: SchemaRegistry,
        endpoints: tuple[str, ...],
    ) -> tuple[str, ...]:
        del registry, endpoints
        return ("snap_001",)

    def load_batch(
        self,
        registry: SchemaRegistry,
        snapshot_id: str,
    ) -> SnapshotBatch:
        del registry, snapshot_id
        return build_stored_snapshot_batch(
            replay_snapshot(),
            (replay_row(),),
            replay_schema(),
        )


class _CanonicalSink:
    def __init__(self) -> None:
        self.artifact_ids: list[str] = []

    def write(
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

    # When: the model-independent rematerialization orchestration executes.
    result = rematerialize_batches(
        replay_registry(),
        ("daily",),
        _Reader(),
        sink,
        projector,
    )

    # Then: one deterministic canonical artifact and one projection are audited.
    assert result == RematerializationResult(
        batch_count=1,
        record_count=1,
        canonical_inserted_count=0,
        event_count=1,
        event_inserted_count=0,
    )
    assert len(sink.artifact_ids) == 1
    assert projector.batch_count == 1


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
