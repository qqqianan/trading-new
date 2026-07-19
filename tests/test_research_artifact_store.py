from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from ashare_lab.research.artifacts import (
    ArtifactFieldMapping,
    ArtifactKind,
    ArtifactWriteRequest,
    ParquetArtifactStore,
    ResearchArtifactError,
    ResearchSchemaCatalog,
)

ROOT = Path(__file__).parents[1]
SCHEMA_PATHS = (
    ROOT / "schemas" / "research_feature_row_v1.json",
    ROOT / "schemas" / "research_label_row_v1.json",
    ROOT / "schemas" / "research_universe_row_v1.json",
    ROOT / "schemas" / "research_dataset_row_v1.json",
)


def _catalog() -> ResearchSchemaCatalog:
    return ResearchSchemaCatalog.load(SCHEMA_PATHS)


def _store(root: Path) -> ParquetArtifactStore:
    return ParquetArtifactStore(root, _catalog())


def _request(
    kind: Literal[ArtifactKind.FEATURE, ArtifactKind.LABEL] = ArtifactKind.FEATURE,
) -> ArtifactWriteRequest:
    field_names = _frame_for(kind).columns
    return ArtifactWriteRequest(
        kind=kind,
        schema_manifest_id=_catalog().schema(kind).manifest_id,
        upstream_artifact_ids=("snap_001",),
        upstream_lineage_edge_ids=("lineage_001",),
        field_mappings=tuple(
            ArtifactFieldMapping(
                output_field=name,
                upstream_artifact_id="snap_001",
                upstream_field=name,
                transformation="identity_or_registered_derivation",
            )
            for name in field_names
        ),
        transform_name="market_factor_materialization",
        transform_version="1.0.0",
        parameters_sha256="a" * 64,
        code_commit="b" * 40,
    )


def _frame(value: float = 1.5) -> pl.DataFrame:
    available_at = datetime(2026, 7, 16, 18, tzinfo=ZoneInfo("Asia/Shanghai"))
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "decision_time": [available_at],
            "feature_id": ["mom_20"],
            "feature_version": ["1.0.0"],
            "value": [value],
            "available_at": [available_at],
            "quality_status": ["ACCEPTED"],
            "null_reason": [None],
        },
        schema=_catalog().polars_schema(ArtifactKind.FEATURE),
    )


def _label_frame() -> pl.DataFrame:
    timezone = ZoneInfo("Asia/Shanghai")
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "decision_time": [datetime(2026, 6, 12, 18, tzinfo=timezone)],
            "entry_time": [datetime(2026, 6, 15, 9, 30, tzinfo=timezone)],
            "exit_time": [datetime(2026, 7, 13, 9, 30, tzinfo=timezone)],
            "label_id": ["relative_return_20d"],
            "label_version": ["1.0.0"],
            "value": [0.03],
            "available_at": [datetime(2026, 7, 13, 9, 30, tzinfo=timezone)],
            "null_reason": [None],
            "entry_price_source_snapshot_id": ["snap_entry"],
            "entry_price_source_row_sha256": ["a" * 64],
            "entry_constraint_source_snapshot_id": ["snap_entry_limit"],
            "entry_constraint_source_row_sha256": ["b" * 64],
            "exit_price_source_snapshot_id": ["snap_exit"],
            "exit_price_source_row_sha256": ["c" * 64],
            "exit_constraint_source_snapshot_id": ["snap_exit_limit"],
            "exit_constraint_source_row_sha256": ["d" * 64],
            "benchmark_entry_source_snapshot_id": ["snap_benchmark"],
            "benchmark_entry_source_row_sha256": ["e" * 64],
            "benchmark_exit_source_snapshot_id": ["snap_benchmark"],
            "benchmark_exit_source_row_sha256": ["f" * 64],
        },
        schema=_catalog().polars_schema(ArtifactKind.LABEL),
    )


def _frame_for(
    kind: Literal[ArtifactKind.FEATURE, ArtifactKind.LABEL],
) -> pl.DataFrame:
    match kind:
        case ArtifactKind.FEATURE:
            return _frame()
        case ArtifactKind.LABEL:
            return _label_frame()


def test_artifact_store_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    # Given: one governed feature frame and immutable materialization evidence.
    store = _store(tmp_path)

    # When: identical content is written twice.
    first = store.write(_frame(), _request())
    second = store.write(_frame(), _request())

    # Then: both writes resolve to one content-addressed artifact.
    assert first == second
    assert first.lineage_edge_id.startswith("lineage_")
    assert len(tuple((tmp_path / "feature").iterdir())) == 1


def test_artifact_store_changes_identity_when_data_changes(tmp_path: Path) -> None:
    # Given: one store and a fixed transformation contract.
    store = _store(tmp_path)

    # When: a material feature value changes.
    first = store.write(_frame(1.5), _request())
    second = store.write(_frame(1.6), _request())

    # Then: immutable content receives a different identity.
    assert first.artifact_id != second.artifact_id


def test_artifact_store_physically_separates_features_and_labels(tmp_path: Path) -> None:
    # Given: feature and label requests with the same tabular shape.
    store = _store(tmp_path)

    # When: both artifact kinds are persisted.
    feature = store.write(_frame(), _request(ArtifactKind.FEATURE))
    label = store.write(_label_frame(), _request(ArtifactKind.LABEL))

    # Then: the paths cannot alias across the feature-label boundary.
    assert feature.parquet_path.parent.parent.name == "feature"
    assert label.parquet_path.parent.parent.name == "label"


def test_artifact_store_reads_the_exact_persisted_frame(tmp_path: Path) -> None:
    # Given: a content-addressed feature artifact.
    store = _store(tmp_path)
    descriptor = store.write(_frame(), _request())

    # When: the descriptor is read through the owned store.
    restored = store.read(descriptor)

    # Then: schema and values match the persisted content.
    assert_frame_equal(restored, _frame())


def test_artifact_payload_is_queryable_by_duckdb(tmp_path: Path) -> None:
    # Given: one immutable Parquet feature artifact.
    descriptor = _store(tmp_path).write(_frame(), _request())

    # When: the analytics engine queries the artifact without a pandas conversion.
    with duckdb.connect(":memory:") as connection:
        row = connection.execute(
            "SELECT symbol, value FROM read_parquet(?)",
            [str(descriptor.parquet_path)],
        ).fetchone()

    # Then: the real Parquet surface exposes the expected typed values.
    assert row == ("000001.SZ", 1.5)


def test_artifact_store_rejects_missing_lineage(tmp_path: Path) -> None:
    # Given: a request that cannot trace its feature to an upstream artifact.
    store = _store(tmp_path)
    request = _request().model_copy(update={"upstream_lineage_edge_ids": ()})

    # When / Then: no untraceable artifact is written.
    with pytest.raises(ResearchArtifactError, match="missing_lineage"):
        store.write(_frame(), request)


def test_artifact_store_rejects_missing_field_lineage(tmp_path: Path) -> None:
    # Given: upstream artifacts without mappings for the materialized columns.
    store = _store(tmp_path)
    request = _request().model_copy(update={"field_mappings": ()})

    # When / Then: table-level provenance cannot replace field-level lineage.
    with pytest.raises(ResearchArtifactError, match="missing_lineage"):
        store.write(_frame(), request)


def test_artifact_store_rejects_partial_field_lineage(tmp_path: Path) -> None:
    # Given: mappings that silently omit one materialized feature column.
    store = _store(tmp_path)
    request = _request()
    partial = request.model_copy(update={"field_mappings": request.field_mappings[:-1]})

    # When / Then: every output field must have an explicit upstream mapping.
    with pytest.raises(ResearchArtifactError, match="missing_lineage"):
        store.write(_frame(), partial)


def test_artifact_store_rejects_corrupted_existing_content(tmp_path: Path) -> None:
    # Given: an artifact whose Parquet bytes were changed after publication.
    store = _store(tmp_path)
    descriptor = store.write(_frame(), _request())
    descriptor.parquet_path.write_bytes(b"corrupted")

    # When / Then: idempotent replay detects the stale artifact instead of overwriting it.
    with pytest.raises(ResearchArtifactError, match="content_mismatch"):
        store.write(_frame(), _request())


def test_artifact_store_rejects_truncated_payload_on_read(tmp_path: Path) -> None:
    # Given: a published artifact truncated after its manifest was committed.
    store = _store(tmp_path)
    descriptor = store.write(_frame(), _request())
    payload = descriptor.parquet_path.read_bytes()
    descriptor.parquet_path.write_bytes(payload[: len(payload) // 2])

    # When / Then: readers fail closed before exposing partial rows.
    with pytest.raises(ResearchArtifactError, match="content_mismatch"):
        store.read(descriptor)


def test_artifact_store_rejects_unregistered_schema(tmp_path: Path) -> None:
    # Given: a feature frame whose request names an unregistered schema identity.
    store = _store(tmp_path)
    request = _request().model_copy(update={"schema_manifest_id": "schema_deadbeef"})

    # When / Then: callers cannot bypass the committed row contract.
    with pytest.raises(ResearchArtifactError, match="schema_mismatch"):
        store.write(_frame(), request)


def test_artifact_store_rejects_schema_drift(tmp_path: Path) -> None:
    # Given: a registered feature request with a renamed dynamic column.
    store = _store(tmp_path)
    drifted = _frame().rename({"value": "factor_value"})

    # When / Then: exact registered columns are required before publication.
    with pytest.raises(ResearchArtifactError, match="schema_mismatch"):
        store.write(drifted, _request())


def test_artifact_store_rejects_cross_kind_descriptor(tmp_path: Path) -> None:
    # Given: a real feature artifact relabeled by a caller as a label descriptor.
    store = _store(tmp_path)
    feature = store.write(_frame(), _request())
    relabeled = feature.model_copy(update={"kind": ArtifactKind.LABEL})

    # When / Then: label reads cannot cross the physical artifact boundary.
    with pytest.raises(ResearchArtifactError, match="content_mismatch"):
        store.read(relabeled)
