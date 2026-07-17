"""Bounded orchestration for full-history weekly PIT universe artifacts."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Protocol

import polars as pl

from ashare_lab.data.universe import SecurityEvent
from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ParquetArtifactStore,
    ResearchSchemaCatalog,
)
from ashare_lab.research.calendar import weekly_decision_times
from ashare_lab.research.universe import (
    UniverseAdmissionSpec,
    UniverseMarketObservation,
    build_universe_panel,
)
from ashare_lab.research.universe.materialization import (
    UniverseMaterializationRequest,
    materialize_universe_frame,
    universe_panel_frame,
)

_DEFAULT_SPEC: Final = UniverseAdmissionSpec()


class UniverseEvidenceReader(Protocol):
    """Read-only governed evidence capability used by the service."""

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        """Load accepted open sessions from one exact schema."""
        ...

    def events(
        self,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[SecurityEvent, ...]:
        """Load accepted PIT lifecycle events visible by the interval end."""
        ...

    def observations(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[UniverseMarketObservation, ...]:
        """Load accepted daily observations for one bounded batch."""
        ...


@dataclass(frozen=True, slots=True)
class UniverseMaterializationResult:
    """Published artifact and bounded orchestration counts."""

    artifact: ArtifactDescriptor
    decision_count: int
    row_count: int
    batch_count: int
    universe_version: str


@dataclass(frozen=True, slots=True)
class UniverseRunRequest:
    """Closed interval, schemas, lineage closure, and admission contract."""

    start_date: date
    end_date: date
    market_schema_manifest_id: str
    universe_schema_manifest_id: str
    materialization: UniverseMaterializationRequest
    admission: UniverseAdmissionSpec = _DEFAULT_SPEC


def materialize_weekly_universe(
    reader: UniverseEvidenceReader,
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    request: UniverseRunRequest,
) -> UniverseMaterializationResult:
    """Read market data by quarter and publish one closed universe artifact."""
    spec = request.admission
    open_dates = reader.open_dates(
        request.start_date,
        request.end_date + timedelta(days=7),
        request.market_schema_manifest_id,
    )
    decisions = weekly_decision_times(
        open_dates,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    events = reader.events(request.end_date, request.universe_schema_manifest_id)
    groups = _quarter_groups(decisions)
    date_positions = {day: index for index, day in enumerate(open_dates)}
    frames: list[pl.DataFrame] = []
    for group in groups:
        first_position = date_positions[group[0].date()]
        lookback_sessions = max(spec.market_window_sessions, spec.liquidity_window_sessions)
        history_position = max(0, first_position - lookback_sessions + 1)
        observations = reader.observations(
            open_dates[history_position],
            group[-1].date(),
            request.market_schema_manifest_id,
        )
        rows = build_universe_panel(events, observations, open_dates, group, spec)
        frames.append(universe_panel_frame(schemas, rows))
    frame = pl.concat(frames) if frames else universe_panel_frame(schemas, ())
    artifact = materialize_universe_frame(
        store,
        schemas,
        frame,
        request.materialization,
        spec,
    )
    return UniverseMaterializationResult(
        artifact=artifact,
        decision_count=len(decisions),
        row_count=frame.height,
        batch_count=len(groups),
        universe_version=spec.version_id,
    )


def _quarter_groups(
    decisions: tuple[datetime, ...],
) -> tuple[tuple[datetime, ...], ...]:
    grouped: defaultdict[tuple[int, int], list[datetime]] = defaultdict(list)
    for decision in decisions:
        grouped[(decision.year, (decision.month - 1) // 3)].append(decision)
    return tuple(tuple(values) for values in grouped.values())
