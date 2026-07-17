from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.universe import SecurityEvent, SecurityEventType
from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.universe import UniverseMarketObservation
from ashare_lab.research.universe.materialization import UniverseMaterializationRequest
from ashare_lab.services.universe_materialization import (
    UniverseRunRequest,
    materialize_weekly_universe,
)

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class EvidenceReader:
    def __init__(
        self,
        open_dates: tuple[date, ...],
        events: tuple[SecurityEvent, ...],
        observations: tuple[UniverseMarketObservation, ...],
    ) -> None:
        self._open_dates = open_dates
        self._events = events
        self._observations = observations
        self.observation_reads = 0

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        assert start_date <= end_date
        assert schema_manifest_id
        return self._open_dates

    def events(
        self,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[SecurityEvent, ...]:
        assert end_date >= self._open_dates[0]
        assert schema_manifest_id
        return self._events

    def observations(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[UniverseMarketObservation, ...]:
        self.observation_reads += 1
        assert schema_manifest_id
        return tuple(
            item for item in self._observations if start_date <= item.trading_date <= end_date
        )


def test_universe_service_batches_market_reads_and_publishes_one_artifact(
    tmp_path: Path,
) -> None:
    # Given: enough governed sessions to cross two calendar quarters.
    dates = _open_dates(130)
    events = (
        _event(SecurityEventType.LISTED, dates[0]),
        _event(SecurityEventType.NAME_STATUS, dates[0], name="平安银行", is_st=False),
    )
    observations = tuple(
        UniverseMarketObservation(
            symbol="000001.SZ",
            trading_date=day,
            available_at=datetime.combine(day, time(16), SHANGHAI),
            amount_cny=25_000_000.0,
            quality_status="ACCEPTED",
            source_artifact_id=f"daily_{day:%Y%m%d}",
        )
        for day in dates
    )
    reader = EvidenceReader(dates, events, observations)
    catalog = ResearchSchemaCatalog.load((ROOT / "schemas" / "research_universe_row_v1.json",))
    store = ParquetArtifactStore(tmp_path, catalog)

    # When: the orchestration materializes the full interval.
    result = materialize_weekly_universe(
        reader,
        store,
        catalog,
        UniverseRunRequest(
            start_date=dates[0],
            end_date=dates[-1],
            market_schema_manifest_id="schema_market",
            universe_schema_manifest_id="schema_universe",
            materialization=UniverseMaterializationRequest(
                input_manifest_id="inputs_001",
                input_lineage_manifest_id="lineage_manifest_001",
                code_commit="a" * 40,
            ),
        ),
    )

    # Then: bounded reads feed one immutable artifact with one row per weekly decision.
    assert reader.observation_reads > 1
    assert result.decision_count == result.artifact.row_count
    assert result.artifact.row_count > 20


def _open_dates(count: int) -> tuple[date, ...]:
    values: list[date] = []
    current = date(2025, 1, 2)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


def _event(
    event_type: SecurityEventType,
    day: date,
    *,
    name: str | None = None,
    is_st: bool | None = None,
) -> SecurityEvent:
    at = datetime.combine(day, time(9, 25), SHANGHAI)
    identity = f"{event_type.value}_{day:%Y%m%d}_{name or 'none'}"
    return SecurityEvent(
        event_id=identity,
        ts_code="000001.SZ",
        event_type=event_type,
        effective_at=at,
        available_at=at,
        ingested_at=at,
        name=name,
        is_st=is_st,
        source_endpoint="fixture",
        source_snapshot_id=f"snapshot_{identity}",
        source_row_sha256="a" * 64,
        input_schema_manifest_id="schema_input",
        schema_manifest_id="schema_universe",
        transform_name="fixture",
        transform_version="1.0.0",
        quality_status="ACCEPTED",
        quality_report_id=f"quality_{identity}",
    )
