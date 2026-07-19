from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ParquetArtifactStore,
    ResearchSchemaCatalog,
)
from ashare_lab.research.labels.materialization import LabelMaterializationRequest
from ashare_lab.research.labels.models import BenchmarkOpenObservation, LabelTradeObservation
from ashare_lab.research.universe import UniversePanelRow
from ashare_lab.research.universe.materialization import (
    UniverseMaterializationRequest,
    materialize_universe_panel,
)
from ashare_lab.services.label_contracts import LabelRunRequest
from ashare_lab.services.label_materialization import materialize_weekly_labels
from tests.test_labels import benchmark_observation, label_sessions, stock_observation

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class LabelEvidenceReader:
    def __init__(
        self,
        sessions: tuple[date, ...],
        stocks: tuple[LabelTradeObservation, ...],
        benchmarks: tuple[BenchmarkOpenObservation, ...],
    ) -> None:
        self._sessions = sessions
        self._stocks = stocks
        self._benchmarks = benchmarks
        self.stock_reads = 0

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        assert start_date <= end_date
        assert schema_manifest_id == "schema_market"
        return tuple(day for day in self._sessions if start_date <= day <= end_date)

    def stock_observations(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[LabelTradeObservation, ...]:
        assert schema_manifest_id == "schema_market"
        self.stock_reads += 1
        return tuple(item for item in self._stocks if start_date <= item.trading_date <= end_date)

    def benchmark_observations(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        schema_manifest_id: str,
    ) -> tuple[BenchmarkOpenObservation, ...]:
        assert symbol == "000905.SH"
        assert schema_manifest_id == "schema_benchmark"
        return tuple(
            item for item in self._benchmarks if start_date <= item.trading_date <= end_date
        )


def test_label_service_preserves_every_universe_key_and_future_null_reason(
    tmp_path: Path,
) -> None:
    # Given: one complete symbol and one symbol missing its fixed exit price.
    sessions = label_sessions(date(2025, 1, 3), 22)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    entry_date, exit_date = sessions[1], sessions[21]
    first_entry = stock_observation(entry_date, 100.0)
    first_exit = stock_observation(exit_date, 110.0)
    second_entry = _for_symbol(stock_observation(entry_date, 50.0), "000002.SZ")
    stocks = tuple(item for item in (first_entry, first_exit, second_entry) if item is not None)
    benchmarks = tuple(
        item
        for item in (
            benchmark_observation(entry_date, 1_000.0),
            benchmark_observation(exit_date, 1_050.0),
        )
        if item is not None
    )
    catalog, store, universe = _universe(tmp_path, decision)

    # When: the service materializes the complete target panel.
    result = materialize_weekly_labels(
        LabelEvidenceReader(sessions, stocks, benchmarks),
        store,
        catalog,
        LabelRunRequest(
            start_date=decision.date(),
            end_date=decision.date(),
            evidence_end_date=sessions[-1],
            market_schema_manifest_id="schema_market",
            benchmark_schema_manifest_id="schema_benchmark",
            universe_artifact=universe,
            materialization=LabelMaterializationRequest(
                input_manifest_id="inputs_001",
                input_lineage_manifest_id="lineage_inputs_001",
                universe_artifact_id=universe.artifact_id,
                universe_lineage_edge_id=universe.lineage_edge_id,
                code_commit="a" * 40,
            ),
        ),
    )

    # Then: the valid target and explicit missing exit coexist without sample deletion.
    frame = store.read(result.artifact).sort("symbol")
    assert result.universe_key_count == 2
    assert result.row_count == 2
    assert frame["value"][0] is not None
    assert frame["null_reason"].to_list() == [None, "MISSING_EXIT_BAR"]


def test_label_service_keeps_recent_decisions_without_complete_future_window(
    tmp_path: Path,
) -> None:
    # Given: the evidence cutoff has fewer than 21 sessions after the decision.
    sessions = label_sessions(date(2025, 1, 3), 8)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    catalog, store, universe = _universe(tmp_path, decision, one_symbol=True)

    # When: the cutoff-bounded service materializes the recent key.
    result = materialize_weekly_labels(
        LabelEvidenceReader(sessions, (), ()),
        store,
        catalog,
        _request(universe, decision, sessions[-1]),
    )

    # Then: the unavailable future is explicit and no source read is fabricated.
    frame = store.read(result.artifact)
    assert frame["null_reason"][0] == "NO_EXIT_SESSION"
    assert frame["available_at"][0] is None


def _universe(
    root: Path,
    decision: datetime,
    *,
    one_symbol: bool = False,
) -> tuple[ResearchSchemaCatalog, ParquetArtifactStore, ArtifactDescriptor]:
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_label_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    store = ParquetArtifactStore(root, catalog)
    symbols = ("000001.SZ",) if one_symbol else ("000001.SZ", "000002.SZ")
    universe = materialize_universe_panel(
        store,
        catalog,
        tuple(
            UniversePanelRow(
                symbol=symbol,
                decision_time=decision,
                available_at=decision - timedelta(hours=1),
                eligible_for_new_risk=True,
                must_continue_marking=True,
                reason_codes=(),
            )
            for symbol in symbols
        ),
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )
    return catalog, store, universe


def _request(
    universe: ArtifactDescriptor,
    decision: datetime,
    evidence_end: date,
) -> LabelRunRequest:
    return LabelRunRequest(
        start_date=decision.date(),
        end_date=decision.date(),
        evidence_end_date=evidence_end,
        market_schema_manifest_id="schema_market",
        benchmark_schema_manifest_id="schema_benchmark",
        universe_artifact=universe,
        materialization=LabelMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            universe_artifact_id=universe.artifact_id,
            universe_lineage_edge_id=universe.lineage_edge_id,
            code_commit="a" * 40,
        ),
    )


def _for_symbol(
    observation: LabelTradeObservation | None,
    symbol: str,
) -> LabelTradeObservation | None:
    if observation is None:
        return None
    return LabelTradeObservation(
        symbol=symbol,
        trading_date=observation.trading_date,
        open_price=observation.open_price,
        up_limit=observation.up_limit,
        down_limit=observation.down_limit,
        is_suspended=observation.is_suspended,
        available_at=observation.available_at,
        price_source_snapshot_id=observation.price_source_snapshot_id,
        price_source_row_sha256=observation.price_source_row_sha256,
        constraint_source_snapshot_id=observation.constraint_source_snapshot_id,
        constraint_source_row_sha256=observation.constraint_source_row_sha256,
    )
