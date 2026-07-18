"""Bounded orchestration for complete weekly market-factor artifacts."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import polars as pl
from pydantic import ValidationError

from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ParquetArtifactStore,
    ResearchSchemaCatalog,
)
from ashare_lab.research.features.market.catalog import market_factor_catalog
from ashare_lab.research.features.market.materialization import (
    MarketFeatureMaterializationRequest,
    market_factor_frame,
    materialize_market_factor_frame,
)
from ashare_lab.research.features.market.models import MarketFactorRow
from ashare_lab.services.market_feature_contracts import (
    MarketFeatureEvidenceReader,
    MarketFeatureMaterializationResult,
    MarketFeatureRunRequest,
    MarketFeatureServiceError,
    MarketFeatureServiceRule,
    UniverseFeatureKey,
)
from ashare_lab.services.market_feature_evidence import (
    MarketHistory,
    market_factor_rows,
    merge_market_history,
    prepare_market_evidence,
    retain_market_history,
)

if TYPE_CHECKING:
    from ashare_lab.research.features.market.mongo_contracts import MarketKey


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
    carry: MarketHistory = {}
    previous_batch_end: date | None = None
    with TemporaryDirectory(prefix="market-features-") as temporary_name:
        staging = Path(temporary_name)
        batch_number = 0
        for decision_batch in _quarter_groups(decisions):
            first_expected = tuple(day for day in calendar if day <= decision_batch[0].date())[
                -121:
            ]
            read_start = (
                first_expected[0]
                if previous_batch_end is None
                else next(day for day in calendar if day > previous_batch_end)
            )
            evidence = reader.read(
                read_start,
                decision_batch[-1].date(),
                request.market_schema_manifest_id,
            )
            current, rejected = prepare_market_evidence(evidence)
            observations = merge_market_history(carry, current)
            rejection_keys.update(rejected)
            for decision in decision_batch:
                expected = tuple(day for day in calendar if day <= decision.date())[-121:]
                rows = market_factor_rows(
                    tuple(key for key in universe_keys if key.decision_time == decision),
                    expected,
                    observations,
                    rejected,
                )
                _stage_rows(staging, schemas, rows, batch_number)
                batch_number += 1
            previous_batch_end = decision_batch[-1].date()
            carry = retain_market_history(observations, calendar, previous_batch_end)
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


def _quarter_groups(
    decisions: tuple[datetime, ...],
) -> tuple[tuple[datetime, ...], ...]:
    grouped: defaultdict[tuple[int, int], list[datetime]] = defaultdict(list)
    for decision in decisions:
        grouped[(decision.year, (decision.month - 1) // 3)].append(decision)
    return tuple(tuple(values) for values in grouped.values())


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
