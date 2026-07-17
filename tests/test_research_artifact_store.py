from pathlib import Path

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from ashare_lab.research.artifacts import (
    ArtifactKind,
    ArtifactWriteRequest,
    ParquetArtifactStore,
    ResearchArtifactError,
)


def _request(kind: ArtifactKind = ArtifactKind.FEATURE) -> ArtifactWriteRequest:
    return ArtifactWriteRequest(
        kind=kind,
        schema_manifest_id="schema_abc123",
        upstream_artifact_ids=("snap_001",),
        upstream_lineage_edge_ids=("lineage_001",),
        field_mappings=("feature.value<-canonical_daily_bar.close",),
        transform_name="market_factor_materialization",
        transform_version="1.0.0",
        parameters_sha256="a" * 64,
        code_commit="b" * 40,
    )


def _frame(value: float = 1.5) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "decision_date": ["2026-07-16"],
            "value": [value],
        }
    )


def test_artifact_store_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    # Given: one governed feature frame and immutable materialization evidence.
    store = ParquetArtifactStore(tmp_path)

    # When: identical content is written twice.
    first = store.write(_frame(), _request())
    second = store.write(_frame(), _request())

    # Then: both writes resolve to one content-addressed artifact.
    assert first == second
    assert first.lineage_edge_id.startswith("lineage_")
    assert len(tuple((tmp_path / "feature").iterdir())) == 1


def test_artifact_store_changes_identity_when_data_changes(tmp_path: Path) -> None:
    # Given: one store and a fixed transformation contract.
    store = ParquetArtifactStore(tmp_path)

    # When: a material feature value changes.
    first = store.write(_frame(1.5), _request())
    second = store.write(_frame(1.6), _request())

    # Then: immutable content receives a different identity.
    assert first.artifact_id != second.artifact_id


def test_artifact_store_physically_separates_features_and_labels(tmp_path: Path) -> None:
    # Given: feature and label requests with the same tabular shape.
    store = ParquetArtifactStore(tmp_path)

    # When: both artifact kinds are persisted.
    feature = store.write(_frame(), _request(ArtifactKind.FEATURE))
    label = store.write(_frame(), _request(ArtifactKind.LABEL))

    # Then: the paths cannot alias across the feature-label boundary.
    assert feature.parquet_path.parent.parent.name == "feature"
    assert label.parquet_path.parent.parent.name == "label"


def test_artifact_store_reads_the_exact_persisted_frame(tmp_path: Path) -> None:
    # Given: a content-addressed feature artifact.
    store = ParquetArtifactStore(tmp_path)
    descriptor = store.write(_frame(), _request())

    # When: the descriptor is read through the owned store.
    restored = store.read(descriptor)

    # Then: schema and values match the persisted content.
    assert_frame_equal(restored, _frame())


def test_artifact_payload_is_queryable_by_duckdb(tmp_path: Path) -> None:
    # Given: one immutable Parquet feature artifact.
    descriptor = ParquetArtifactStore(tmp_path).write(_frame(), _request())

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
    store = ParquetArtifactStore(tmp_path)
    request = _request().model_copy(update={"upstream_lineage_edge_ids": ()})

    # When / Then: no untraceable artifact is written.
    with pytest.raises(ResearchArtifactError, match="missing_lineage"):
        store.write(_frame(), request)


def test_artifact_store_rejects_missing_field_lineage(tmp_path: Path) -> None:
    # Given: upstream artifacts without mappings for the materialized columns.
    store = ParquetArtifactStore(tmp_path)
    request = _request().model_copy(update={"field_mappings": ()})

    # When / Then: table-level provenance cannot replace field-level lineage.
    with pytest.raises(ResearchArtifactError, match="missing_lineage"):
        store.write(_frame(), request)


def test_artifact_store_rejects_corrupted_existing_content(tmp_path: Path) -> None:
    # Given: an artifact whose Parquet bytes were changed after publication.
    store = ParquetArtifactStore(tmp_path)
    descriptor = store.write(_frame(), _request())
    descriptor.parquet_path.write_bytes(b"corrupted")

    # When / Then: idempotent replay detects the stale artifact instead of overwriting it.
    with pytest.raises(ResearchArtifactError, match="content_mismatch"):
        store.write(_frame(), _request())
