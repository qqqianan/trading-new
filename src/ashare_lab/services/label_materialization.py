"""Bounded orchestration for the complete weekly future-label panel."""

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
from pydantic import ValidationError

from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.labels.calculator import (
    calculate_relative_open_return,
    resolve_label_window,
)
from ashare_lab.research.labels.catalog import medium_horizon_label
from ashare_lab.research.labels.materialization import (
    label_frame,
    materialize_label_frame,
)
from ashare_lab.research.labels.models import (
    BenchmarkOpenObservation,
    LabelTradeObservation,
    LabelWindow,
    LabelWindowEvidence,
)
from ashare_lab.services.label_contracts import (
    LabelEvidenceReader,
    LabelMaterializationResult,
    LabelRunRequest,
    LabelServiceError,
    LabelServiceRule,
    LabelUniverseKey,
)


def materialize_weekly_labels(
    reader: LabelEvidenceReader,
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    request: LabelRunRequest,
) -> LabelMaterializationResult:
    """Preserve every universe key while publishing one isolated target."""
    _validate_identity(request)
    universe = store.read(request.universe_artifact).filter(
        pl.col("decision_time").dt.date().is_between(request.start_date, request.end_date)
    )
    keys = _universe_keys(universe)
    decisions = tuple(sorted({key.decision_time for key in keys}))
    calendar = reader.open_dates(
        request.start_date,
        request.evidence_end_date,
        request.market_schema_manifest_id,
    )
    _validate_calendar(calendar, decisions)
    by_decision = _group_keys(keys)
    with TemporaryDirectory(prefix="labels-") as temporary_name:
        staging = Path(temporary_name)
        for batch_number, batch in enumerate(_quarter_groups(decisions)):
            windows = {decision: resolve_label_window(calendar, decision) for decision in batch}
            stocks, benchmarks = _batch_evidence(reader, request, windows)
            rows = tuple(
                calculate_relative_open_return(
                    key.symbol,
                    decision,
                    windows[decision],
                    LabelWindowEvidence(
                        _stock_at(stocks, key.symbol, windows[decision].entry_date),
                        _stock_at(stocks, key.symbol, windows[decision].exit_date),
                        _benchmark_at(benchmarks, windows[decision].entry_date),
                        _benchmark_at(benchmarks, windows[decision].exit_date),
                    ),
                )
                for decision in batch
                for key in by_decision[decision]
            )
            label_frame(schemas, rows).write_parquet(
                staging / f"{batch_number:04d}.parquet",
                compression="zstd",
            )
        frame = pl.scan_parquet(staging / "*.parquet").collect(engine="streaming")
        artifact = materialize_label_frame(store, schemas, frame, request.materialization)
    return LabelMaterializationResult(artifact, len(decisions), len(keys), artifact.row_count)


def _batch_evidence(
    reader: LabelEvidenceReader,
    request: LabelRunRequest,
    windows: dict[datetime, LabelWindow],
) -> tuple[
    dict[tuple[str, date], LabelTradeObservation],
    dict[date, BenchmarkOpenObservation],
]:
    dates = tuple(
        day
        for window in windows.values()
        if window.entry_date is not None and window.exit_date is not None
        for day in (window.entry_date, window.exit_date)
    )
    if not dates:
        return {}, {}
    start_date, end_date = min(dates), max(dates)
    stocks = reader.stock_observations(
        start_date,
        end_date,
        request.market_schema_manifest_id,
    )
    definition = medium_horizon_label()
    benchmarks = reader.benchmark_observations(
        start_date,
        end_date,
        definition.benchmark_symbol,
        request.benchmark_schema_manifest_id,
    )
    stock_map = {(item.symbol, item.trading_date): item for item in stocks}
    benchmark_map = {item.trading_date: item for item in benchmarks}
    if len(stock_map) != len(stocks) or len(benchmark_map) != len(benchmarks):
        raise LabelServiceError(
            LabelServiceRule.DUPLICATE_SOURCE_EVIDENCE,
            "stock or benchmark observations contain duplicate natural keys",
        )
    return stock_map, benchmark_map


def _stock_at(
    observations: dict[tuple[str, date], LabelTradeObservation],
    symbol: str,
    trading_date: date | None,
) -> LabelTradeObservation | None:
    if trading_date is None:
        return None
    return observations.get((symbol, trading_date))


def _benchmark_at(
    observations: dict[date, BenchmarkOpenObservation],
    trading_date: date | None,
) -> BenchmarkOpenObservation | None:
    if trading_date is None:
        return None
    return observations.get(trading_date)


def _validate_identity(request: LabelRunRequest) -> None:
    artifact = request.universe_artifact
    materialization = request.materialization
    if (
        artifact.artifact_id != materialization.universe_artifact_id
        or artifact.lineage_edge_id != materialization.universe_lineage_edge_id
    ):
        raise LabelServiceError(
            LabelServiceRule.UNIVERSE_IDENTITY_MISMATCH,
            artifact.artifact_id,
        )


def _universe_keys(frame: pl.DataFrame) -> tuple[LabelUniverseKey, ...]:
    try:
        keys = tuple(LabelUniverseKey.model_validate(row) for row in frame.to_dicts())
    except ValidationError as error:
        raise LabelServiceError(
            LabelServiceRule.INVALID_UNIVERSE_EVIDENCE,
            str(error),
        ) from error
    identities = tuple((key.symbol, key.decision_time) for key in keys)
    if not keys or len(identities) != len(set(identities)):
        raise LabelServiceError(
            LabelServiceRule.INVALID_UNIVERSE_EVIDENCE,
            "universe interval is empty or contains duplicate keys",
        )
    return keys


def _validate_calendar(calendar: tuple[date, ...], decisions: tuple[datetime, ...]) -> None:
    if tuple(sorted(set(calendar))) != calendar:
        raise LabelServiceError(
            LabelServiceRule.INVALID_CALENDAR_EVIDENCE,
            "open sessions must be unique and strictly increasing",
        )
    missing = tuple(item.date() for item in decisions if item.date() not in calendar)
    if missing:
        raise LabelServiceError(
            LabelServiceRule.INVALID_CALENDAR_EVIDENCE,
            f"decision session is absent: {missing[0]:%Y%m%d}",
        )


def _group_keys(keys: tuple[LabelUniverseKey, ...]) -> dict[datetime, tuple[LabelUniverseKey, ...]]:
    grouped: defaultdict[datetime, list[LabelUniverseKey]] = defaultdict(list)
    for key in keys:
        grouped[key.decision_time].append(key)
    return {decision: tuple(grouped[decision]) for decision in sorted(grouped)}


def _quarter_groups(decisions: tuple[datetime, ...]) -> tuple[tuple[datetime, ...], ...]:
    grouped: defaultdict[tuple[int, int], list[datetime]] = defaultdict(list)
    for decision in decisions:
        grouped[(decision.year, (decision.month - 1) // 3)].append(decision)
    return tuple(tuple(values) for values in grouped.values())
