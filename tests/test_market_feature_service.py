from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.features.market.materialization import (
    MarketFeatureMaterializationRequest,
)
from ashare_lab.research.features.market.mongo_contracts import MarketBundleReadResult
from ashare_lab.research.universe import UniversePanelRow
from ashare_lab.research.universe.materialization import (
    UniverseMaterializationRequest,
    materialize_universe_panel,
)
from ashare_lab.services.market_feature_materialization import (
    MarketFeatureRunRequest,
    MarketFeatureServiceError,
    materialize_weekly_market_features,
)
from tests.test_market_factors import market_observations

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketEvidenceReader:
    def __init__(self, open_dates: tuple[date, ...]) -> None:
        self._open_dates = open_dates
        self.read_count = 0
        self.read_ranges: list[tuple[date, date]] = []
        complete = market_observations(len(open_dates))
        missing_day = open_dates[-10]
        self._observations = tuple(
            item for item in complete if item.bar.trading_date != missing_day
        )

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        assert start_date <= end_date
        assert schema_manifest_id
        return self._open_dates

    def read(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> MarketBundleReadResult:
        assert schema_manifest_id
        self.read_count += 1
        self.read_ranges.append((start_date, end_date))
        return MarketBundleReadResult(
            observations=tuple(
                item
                for item in self._observations
                if start_date <= item.bar.trading_date <= end_date
            ),
            rejections=(),
            suspended_keys=(),
        )


def test_market_feature_service_preserves_missing_sessions_and_decision_bars(
    tmp_path: Path,
) -> None:
    # Given: one symbol has a historical gap and another has no decision-date bar.
    dates = _open_dates(21)
    decision = datetime.combine(dates[-1], time(18), SHANGHAI)
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    store = ParquetArtifactStore(tmp_path, catalog)
    universe = materialize_universe_panel(
        store,
        catalog,
        (
            _universe_row("000001.SZ", decision),
            _universe_row("000002.SZ", decision),
        ),
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )

    # When: the governed service materializes every universe key.
    result = materialize_weekly_market_features(
        MarketEvidenceReader(dates),
        store,
        catalog,
        MarketFeatureRunRequest(
            start_date=dates[-1],
            end_date=dates[-1],
            market_schema_manifest_id="schema_market",
            universe_artifact=universe,
            materialization=MarketFeatureMaterializationRequest(
                input_manifest_id="inputs_001",
                input_lineage_manifest_id="lineage_inputs_001",
                universe_artifact_id=universe.artifact_id,
                universe_lineage_edge_id=universe.lineage_edge_id,
                code_commit="a" * 40,
            ),
        ),
    )

    # Then: no key disappears and each failure has a stable reason.
    assert result.row_count == 30
    mom = store.read(next(item for item in result.artifacts if item.row_count == 2))
    first = mom.filter(mom["symbol"] == "000001.SZ").row(0, named=True)
    second = mom.filter(mom["symbol"] == "000002.SZ").row(0, named=True)
    assert first["null_reason"] == "MISSING_TRADING_SESSION"
    assert second["null_reason"] == "MISSING_DECISION_BAR"


def test_market_feature_service_rejects_universe_lineage_alias(tmp_path: Path) -> None:
    # Given: the run claims a different universe artifact than the one being read.
    dates = _open_dates(21)
    decision = datetime.combine(dates[-1], time(18), SHANGHAI)
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    store = ParquetArtifactStore(tmp_path, catalog)
    universe = materialize_universe_panel(
        store,
        catalog,
        (_universe_row("000001.SZ", decision),),
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )
    request = MarketFeatureRunRequest(
        start_date=dates[-1],
        end_date=dates[-1],
        market_schema_manifest_id="schema_market",
        universe_artifact=universe,
        materialization=MarketFeatureMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            universe_artifact_id="universe_artifact_wrong",
            universe_lineage_edge_id=universe.lineage_edge_id,
            code_commit="a" * 40,
        ),
    )

    # When / Then: mismatched lineage closes the gate before factor publication.
    with pytest.raises(MarketFeatureServiceError, match="universe_identity_mismatch"):
        materialize_weekly_market_features(MarketEvidenceReader(dates), store, catalog, request)


def test_market_feature_service_rejects_late_universe_evidence(tmp_path: Path) -> None:
    # Given: an immutable universe row claims evidence from after its decision.
    dates = _open_dates(21)
    decision = datetime.combine(dates[-1], time(18), SHANGHAI)
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    store = ParquetArtifactStore(tmp_path, catalog)
    late_row = replace(
        _universe_row("000001.SZ", decision),
        available_at=decision + timedelta(seconds=1),
    )
    universe = materialize_universe_panel(
        store,
        catalog,
        (late_row,),
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )
    request = MarketFeatureRunRequest(
        start_date=dates[-1],
        end_date=dates[-1],
        market_schema_manifest_id="schema_market",
        universe_artifact=universe,
        materialization=MarketFeatureMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            universe_artifact_id=universe.artifact_id,
            universe_lineage_edge_id=universe.lineage_edge_id,
            code_commit="a" * 40,
        ),
    )

    # When / Then: the service rejects the leaked key before any market read.
    with pytest.raises(MarketFeatureServiceError, match="invalid_universe_evidence"):
        materialize_weekly_market_features(MarketEvidenceReader(dates), store, catalog, request)


def test_market_feature_service_reuses_one_quarterly_bundle_read(tmp_path: Path) -> None:
    # Given: two weekly decisions share one calendar quarter.
    dates = _open_dates(21)
    decisions = tuple(datetime.combine(day, time(18), SHANGHAI) for day in dates[-6::5])
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    store = ParquetArtifactStore(tmp_path, catalog)
    universe = materialize_universe_panel(
        store,
        catalog,
        tuple(_universe_row("000001.SZ", decision) for decision in decisions),
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )
    reader = MarketEvidenceReader(dates)

    # When: the service materializes both decisions.
    result = materialize_weekly_market_features(
        reader,
        store,
        catalog,
        MarketFeatureRunRequest(
            start_date=decisions[0].date(),
            end_date=decisions[-1].date(),
            market_schema_manifest_id="schema_market",
            universe_artifact=universe,
            materialization=MarketFeatureMaterializationRequest(
                input_manifest_id="inputs_001",
                input_lineage_manifest_id="lineage_inputs_001",
                universe_artifact_id=universe.artifact_id,
                universe_lineage_edge_id=universe.lineage_edge_id,
                code_commit="a" * 40,
            ),
        ),
    )

    # Then: one bounded read is reused without dropping either decision key.
    assert reader.read_count == 1
    assert result.row_count == 30


def test_market_feature_service_carries_history_without_rereading_prior_quarter(
    tmp_path: Path,
) -> None:
    # Given: two decisions span adjacent quarters with continuous market evidence.
    dates = _open_dates(70)
    decisions = (
        datetime.combine(dates[20], time(18), SHANGHAI),
        datetime.combine(dates[-1], time(18), SHANGHAI),
    )
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    store = ParquetArtifactStore(tmp_path, catalog)
    universe = materialize_universe_panel(
        store,
        catalog,
        tuple(_universe_row("000001.SZ", decision) for decision in decisions),
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )
    reader = MarketEvidenceReader(dates)

    # When: both quarterly groups are materialized.
    materialize_weekly_market_features(
        reader,
        store,
        catalog,
        MarketFeatureRunRequest(
            start_date=decisions[0].date(),
            end_date=decisions[-1].date(),
            market_schema_manifest_id="schema_market",
            universe_artifact=universe,
            materialization=MarketFeatureMaterializationRequest(
                input_manifest_id="inputs_001",
                input_lineage_manifest_id="lineage_inputs_001",
                universe_artifact_id=universe.artifact_id,
                universe_lineage_edge_id=universe.lineage_edge_id,
                code_commit="a" * 40,
            ),
        ),
    )

    # Then: the second read starts after the first batch and relies on carried history.
    assert reader.read_count == 2
    assert reader.read_ranges[0] == (dates[0], decisions[0].date())
    assert reader.read_ranges[1] == (dates[21], decisions[1].date())


def _open_dates(count: int) -> tuple[date, ...]:
    values: list[date] = []
    current = date(2025, 1, 2)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


def _universe_row(symbol: str, decision: datetime) -> UniversePanelRow:
    return UniversePanelRow(
        symbol=symbol,
        decision_time=decision,
        available_at=decision - timedelta(hours=1),
        eligible_for_new_risk=True,
        must_continue_marking=True,
        reason_codes=(),
    )
