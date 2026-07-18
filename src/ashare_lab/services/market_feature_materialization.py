"""Bounded orchestration for complete weekly market-factor artifacts."""

from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
from pydantic import ValidationError

from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ParquetArtifactStore,
    ResearchSchemaCatalog,
)
from ashare_lab.research.features.market.calculator import calculate_market_factors
from ashare_lab.research.features.market.catalog import market_factor_catalog
from ashare_lab.research.features.market.materialization import (
    MarketFeatureMaterializationRequest,
    market_factor_frame,
    materialize_market_factor_frame,
)
from ashare_lab.research.features.market.models import (
    MarketFactorObservation,
    MarketFactorRow,
)
from ashare_lab.research.features.market.mongo_contracts import (
    MarketBundleReadResult,
    MarketKey,
)
from ashare_lab.services.market_feature_contracts import (
    MarketFeatureEvidenceReader,
    MarketFeatureMaterializationResult,
    MarketFeatureRunRequest,
    MarketFeatureServiceError,
    MarketFeatureServiceRule,
    UniverseFeatureKey,
)


def materialize_weekly_market_features(
    reader: MarketFeatureEvidenceReader,
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    request: MarketFeatureRunRequest,
) -> MarketFeatureMaterializationResult:
    """Preserve every universe key while publishing isolated factor artifacts."""
    if request.universe_artifact.artifact_id != request.materialization.universe_artifact_id:
        raise MarketFeatureServiceError(
            MarketFeatureServiceRule.UNIVERSE_IDENTITY_MISMATCH,
            request.universe_artifact.artifact_id,
        )
    universe = store.read(request.universe_artifact).filter(
        pl.col("decision_time").dt.date().is_between(request.start_date, request.end_date)
    )
    universe_keys = _universe_keys(universe)
    decisions = tuple(sorted({key.decision_time for key in universe_keys}))
    calendar = reader.open_dates(
        request.start_date - timedelta(days=200),
        request.end_date,
        request.market_schema_manifest_id,
    )
    _validate_calendar(calendar, decisions)
    rejection_keys: set[MarketKey] = set()
    with TemporaryDirectory(prefix="market-features-") as temporary_name:
        staging = Path(temporary_name)
        batch_number = 0
        for decision_batch in _quarter_groups(decisions):
            first_expected = tuple(day for day in calendar if day <= decision_batch[0].date())[
                -121:
            ]
            evidence = reader.read(
                first_expected[0],
                decision_batch[-1].date(),
                request.market_schema_manifest_id,
            )
            observations, rejected = _prepare_evidence(evidence)
            rejection_keys.update(rejected)
            for decision in decision_batch:
                expected = tuple(day for day in calendar if day <= decision.date())[-121:]
                rows = _rows_from_index(
                    tuple(key for key in universe_keys if key.decision_time == decision),
                    expected,
                    observations,
                    rejected,
                )
                _stage_rows(staging, schemas, rows, batch_number)
                batch_number += 1
        artifacts = _publish_staged(staging, store, schemas, request.materialization)
    return MarketFeatureMaterializationResult(
        artifacts=artifacts,
        decision_count=len(decisions),
        universe_key_count=len(universe_keys),
        row_count=sum(item.row_count for item in artifacts),
        bundle_rejection_count=len(rejection_keys),
    )


def _universe_keys(frame: pl.DataFrame) -> tuple[UniverseFeatureKey, ...]:
    try:
        keys = tuple(UniverseFeatureKey.model_validate(row) for row in frame.to_dicts())
    except ValidationError as error:
        raise MarketFeatureServiceError(
            MarketFeatureServiceRule.INVALID_UNIVERSE_EVIDENCE,
            str(error),
        ) from error
    identities = tuple((key.symbol, key.decision_time) for key in keys)
    if not keys or len(identities) != len(set(identities)):
        raise MarketFeatureServiceError(
            MarketFeatureServiceRule.INVALID_UNIVERSE_EVIDENCE,
            "universe interval is empty or contains duplicate keys",
        )
    return keys


def _validate_calendar(
    calendar: tuple[date, ...],
    decisions: tuple[datetime, ...],
) -> None:
    if tuple(sorted(set(calendar))) != calendar:
        raise MarketFeatureServiceError(
            MarketFeatureServiceRule.INVALID_CALENDAR_EVIDENCE,
            "open sessions must be unique and strictly increasing",
        )
    missing = tuple(decision.date() for decision in decisions if decision.date() not in calendar)
    if missing:
        raise MarketFeatureServiceError(
            MarketFeatureServiceRule.INVALID_CALENDAR_EVIDENCE,
            f"decision sessions are absent: {missing[0]:%Y%m%d}",
        )


def _rows_from_index(
    keys: tuple[UniverseFeatureKey, ...],
    expected_dates: tuple[date, ...],
    observations: dict[str, tuple[MarketFactorObservation, ...]],
    rejected: set[MarketKey],
) -> tuple[MarketFactorRow, ...]:
    expected = set(expected_dates)
    by_symbol: defaultdict[str, list[MarketFactorObservation]] = defaultdict(list)
    for symbol, series in observations.items():
        by_symbol[symbol].extend(item for item in series if item.bar.trading_date in expected)
    rows: list[MarketFactorRow] = []
    for key in keys:
        decision = key.decision_time
        current_key = (key.symbol, decision.date())
        series = tuple(by_symbol[key.symbol])
        if not series or series[-1].bar.trading_date != decision.date():
            reason = (
                "MISSING_REQUIRED_BUNDLE" if current_key in rejected else "MISSING_DECISION_BAR"
            )
            rows.extend(_null_rows(key, reason))
            continue
        rows.extend(calculate_market_factors(series, decision, expected_dates))
    return tuple(rows)


def _prepare_evidence(
    evidence: MarketBundleReadResult,
) -> tuple[dict[str, tuple[MarketFactorObservation, ...]], set[MarketKey]]:
    suspended = set(evidence.suspended_keys)
    indexed: dict[MarketKey, MarketFactorObservation] = {}
    for item in evidence.observations:
        key = (str(item.bar.symbol), item.bar.trading_date)
        if key in indexed:
            raise MarketFeatureServiceError(
                MarketFeatureServiceRule.DUPLICATE_MARKET_OBSERVATION,
                f"{key[0]}:{key[1]:%Y%m%d}",
            )
        indexed[key] = (
            replace(item, bar=replace(item.bar, is_suspended=True)) if key in suspended else item
        )
    grouped: defaultdict[str, list[MarketFactorObservation]] = defaultdict(list)
    for (symbol, _), item in sorted(indexed.items()):
        grouped[symbol].append(item)
    rejected = {(item.symbol, item.trading_date) for item in evidence.rejections}
    return {symbol: tuple(values) for symbol, values in grouped.items()}, rejected


def _quarter_groups(
    decisions: tuple[datetime, ...],
) -> tuple[tuple[datetime, ...], ...]:
    grouped: defaultdict[tuple[int, int], list[datetime]] = defaultdict(list)
    for decision in decisions:
        grouped[(decision.year, (decision.month - 1) // 3)].append(decision)
    return tuple(tuple(values) for values in grouped.values())


def _null_rows(key: UniverseFeatureKey, reason: str) -> tuple[MarketFactorRow, ...]:
    return tuple(
        MarketFactorRow(
            symbol=key.symbol,
            decision_time=key.decision_time,
            feature_id=definition.name,
            feature_version=definition.version,
            value=None,
            available_at=key.available_at,
            quality_status="INCOMPLETE",
            null_reason=reason,
        )
        for definition in market_factor_catalog()
    )


def _stage_rows(
    staging: Path,
    schemas: ResearchSchemaCatalog,
    rows: tuple[MarketFactorRow, ...],
    batch_number: int,
) -> None:
    for definition in market_factor_catalog():
        selected = tuple(row for row in rows if row.feature_id == definition.name)
        directory = staging / definition.name
        directory.mkdir(parents=True, exist_ok=True)
        market_factor_frame(schemas, selected).write_parquet(
            directory / f"{batch_number:04d}.parquet",
            compression="zstd",
        )


def _publish_staged(
    staging: Path,
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    request: MarketFeatureMaterializationRequest,
) -> tuple[ArtifactDescriptor, ...]:
    descriptors: list[ArtifactDescriptor] = []
    for definition in market_factor_catalog():
        frame = pl.scan_parquet(staging / definition.name / "*.parquet").collect(engine="streaming")
        descriptors.append(
            materialize_market_factor_frame(
                store,
                schemas,
                frame,
                definition.name,
                request,
            )
        )
    return tuple(descriptors)
