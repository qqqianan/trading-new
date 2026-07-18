"""Bounded orchestration for complete weekly financial-factor artifacts."""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
from pydantic import ValidationError

from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ParquetArtifactStore,
    ResearchSchemaCatalog,
)
from ashare_lab.research.features.financial.catalog import financial_factor_catalog
from ashare_lab.research.features.financial.materialization import (
    FinancialFeatureMaterializationRequest,
    financial_factor_frame,
    materialize_financial_factor_frame,
)
from ashare_lab.research.features.financial.models import (
    FinancialFactorValue,
    FinancialIndicatorObservation,
)
from ashare_lab.research.features.financial.selector import calculate_financial_factors
from ashare_lab.services.financial_feature_contracts import (
    FinancialFeatureEvidenceReader,
    FinancialFeatureMaterializationResult,
    FinancialFeatureRunRequest,
    FinancialFeatureServiceError,
    FinancialFeatureServiceRule,
    FinancialUniverseKey,
)

__all__ = ["FinancialFeatureServiceError", "materialize_weekly_financial_features"]


def materialize_weekly_financial_features(
    reader: FinancialFeatureEvidenceReader,
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    request: FinancialFeatureRunRequest,
) -> FinancialFeatureMaterializationResult:
    """Preserve every universe key while publishing isolated PIT factors."""
    _validate_identity(request)
    universe = store.read(request.universe_artifact).filter(
        pl.col("decision_time").dt.date().is_between(request.start_date, request.end_date)
    )
    keys = _universe_keys(universe)
    by_decision = _group_keys(keys)
    observations = reader.read(
        max(by_decision),
        request.financial_schema_manifest_id,
    )
    by_symbol = _group_observations(observations)
    with TemporaryDirectory(prefix="financial-features-") as temporary_name:
        staging = Path(temporary_name)
        for batch_number, (decision, decision_keys) in enumerate(by_decision.items()):
            rows = tuple(
                row
                for key in decision_keys
                for row in calculate_financial_factors(
                    by_symbol.get(key.symbol, ()),
                    key.symbol,
                    decision,
                    key.available_at,
                )
            )
            _stage_rows(staging, schemas, rows, batch_number)
        artifacts = _publish_staged(staging, store, schemas, request.materialization)
    return FinancialFeatureMaterializationResult(
        artifacts=artifacts,
        decision_count=len(by_decision),
        universe_key_count=len(keys),
        row_count=sum(item.row_count for item in artifacts),
        financial_version_count=len(observations),
    )


def _validate_identity(request: FinancialFeatureRunRequest) -> None:
    if request.universe_artifact.artifact_id != request.materialization.universe_artifact_id:
        raise FinancialFeatureServiceError(
            FinancialFeatureServiceRule.UNIVERSE_IDENTITY_MISMATCH,
            request.universe_artifact.artifact_id,
        )
    if (
        request.universe_artifact.lineage_edge_id
        != request.materialization.universe_lineage_edge_id
    ):
        raise FinancialFeatureServiceError(
            FinancialFeatureServiceRule.UNIVERSE_IDENTITY_MISMATCH,
            request.universe_artifact.lineage_edge_id,
        )


def _universe_keys(frame: pl.DataFrame) -> tuple[FinancialUniverseKey, ...]:
    try:
        keys = tuple(FinancialUniverseKey.model_validate(row) for row in frame.to_dicts())
    except ValidationError as error:
        raise FinancialFeatureServiceError(
            FinancialFeatureServiceRule.INVALID_UNIVERSE_EVIDENCE,
            str(error),
        ) from error
    identities = tuple((key.symbol, key.decision_time) for key in keys)
    if not keys or len(identities) != len(set(identities)):
        raise FinancialFeatureServiceError(
            FinancialFeatureServiceRule.INVALID_UNIVERSE_EVIDENCE,
            "universe interval is empty or contains duplicate keys",
        )
    return keys


def _group_keys(
    keys: tuple[FinancialUniverseKey, ...],
) -> dict[datetime, tuple[FinancialUniverseKey, ...]]:
    grouped: defaultdict[datetime, list[FinancialUniverseKey]] = defaultdict(list)
    for key in keys:
        grouped[key.decision_time].append(key)
    return {decision: tuple(grouped[decision]) for decision in sorted(grouped)}


def _group_observations(
    observations: tuple[FinancialIndicatorObservation, ...],
) -> dict[str, tuple[FinancialIndicatorObservation, ...]]:
    grouped: defaultdict[str, list[FinancialIndicatorObservation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.symbol].append(observation)
    return {symbol: tuple(values) for symbol, values in grouped.items()}


def _stage_rows(
    staging: Path,
    schemas: ResearchSchemaCatalog,
    rows: tuple[FinancialFactorValue, ...],
    batch_number: int,
) -> None:
    for definition in financial_factor_catalog():
        directory = staging / definition.name
        directory.mkdir(parents=True, exist_ok=True)
        financial_factor_frame(
            schemas,
            tuple(row for row in rows if row.feature_id == definition.name),
        ).write_parquet(directory / f"{batch_number:04d}.parquet", compression="zstd")


def _publish_staged(
    staging: Path,
    store: ParquetArtifactStore,
    schemas: ResearchSchemaCatalog,
    request: FinancialFeatureMaterializationRequest,
) -> tuple[ArtifactDescriptor, ...]:
    descriptors: list[ArtifactDescriptor] = []
    for definition in financial_factor_catalog():
        frame = pl.scan_parquet(staging / definition.name / "*.parquet").collect(engine="streaming")
        descriptors.append(
            materialize_financial_factor_frame(
                store,
                schemas,
                frame,
                definition.name,
                request,
            )
        )
    return tuple(descriptors)
