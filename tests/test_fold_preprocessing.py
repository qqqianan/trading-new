import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from pydantic import ValidationError

from ashare_lab.research.preprocessing.fold import FoldPreprocessingError, FoldPreprocessor
from ashare_lab.research.preprocessing.models import FoldPreprocessingArtifact
from ashare_lab.research.preprocessing.store import (
    FoldPreprocessorStore,
    FoldPreprocessorStoreError,
)

DATASET_ID = "ds_862d155145b89879b679"
ROOT = Path(__file__).parents[1]


def _training_frame() -> pl.DataFrame:
    timezone = ZoneInfo("Asia/Shanghai")
    return pl.DataFrame(
        {
            "decision_time": [
                datetime(2024, 1, 5, 18, tzinfo=timezone),
                datetime(2024, 1, 5, 18, tzinfo=timezone),
                datetime(2024, 1, 12, 18, tzinfo=timezone),
                datetime(2024, 1, 12, 18, tzinfo=timezone),
            ],
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "factor_a": [0.0, 100.0, 2.0, None],
            "log_total_mv": [1.0, 3.0, 2.0, 4.0],
        }
    )


def _validation_frame(extreme: float = 10_000.0) -> pl.DataFrame:
    timezone = ZoneInfo("Asia/Shanghai")
    return pl.DataFrame(
        {
            "decision_time": [
                datetime(2024, 2, 2, 18, tzinfo=timezone),
                datetime(2024, 2, 2, 18, tzinfo=timezone),
                datetime(2024, 2, 2, 18, tzinfo=timezone),
            ],
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "factor_a": [1.0, None, extreme],
            "log_total_mv": [1.5, 2.5, 3.5],
        }
    )


def test_fold_fit_uses_only_training_rows_for_learned_statistics() -> None:
    # Given: a training fold and an extreme validation cross-section.
    preprocessor = FoldPreprocessor(("factor_a",), "log_total_mv")

    # When: the fit artifact is created without passing validation data.
    artifact = preprocessor.fit(_training_frame(), "fold_000", DATASET_ID)

    # Then: winsor and fallback statistics equal the training slice hand calculation.
    stats = artifact.feature_statistics[0]
    assert stats.feature_name == "factor_a"
    assert stats.lower_quantile == pytest.approx(0.04)
    assert stats.upper_quantile == pytest.approx(98.04)
    assert stats.fallback_median == pytest.approx(2.0)
    assert artifact.training_row_count == 4
    assert artifact.dataset_snapshot_id == DATASET_ID
    assert artifact.training_end.isoformat().startswith("2024-01-12")


def test_fold_transform_preserves_rows_and_missing_indicators() -> None:
    # Given: fitted training-only parameters and validation with one missing value.
    preprocessor = FoldPreprocessor(("factor_a",), "log_total_mv")
    artifact = preprocessor.fit(_training_frame(), "fold_000", DATASET_ID)

    # When: the held-out cross-section is transformed without fitting.
    transformed = preprocessor.transform(_validation_frame(), artifact)

    # Then: no sample disappears and the missing observation remains auditable.
    assert transformed.height == 3
    assert transformed["factor_a_missing"].to_list() == [False, True, False]
    assert transformed["factor_a"].null_count() == 0
    assert transformed["symbol"].to_list() == ["000001.SZ", "000002.SZ", "000003.SZ"]


def test_validation_values_cannot_change_fitted_artifact() -> None:
    # Given: one fitted artifact and two materially different validation frames.
    preprocessor = FoldPreprocessor(("factor_a",), "log_total_mv")
    artifact = preprocessor.fit(_training_frame(), "fold_000", DATASET_ID)

    # When: both validation frames are transformed.
    preprocessor.transform(_validation_frame(10_000.0), artifact)
    preprocessor.transform(_validation_frame(1_000_000.0), artifact)

    # Then: the immutable training artifact remains byte-for-byte identical.
    assert artifact == preprocessor.fit(_training_frame(), "fold_000", DATASET_ID)


def test_preprocessing_artifact_store_is_content_addressed(tmp_path: Path) -> None:
    # Given: one fold-local fitted artifact and an immutable local store.
    artifact = FoldPreprocessor(("factor_a",), "log_total_mv").fit(
        _training_frame(),
        "fold_000",
        DATASET_ID,
    )
    store = FoldPreprocessorStore(tmp_path)

    # When: the same artifact is persisted twice.
    first = store.write(artifact)
    second = store.write(artifact)

    # Then: one content identity is reused and verifies on read.
    assert first == second
    assert first.artifact_id.startswith("preprocessor_artifact_")
    assert store.read(first) == artifact


def test_size_factor_is_standardized_but_not_neutralized_against_itself() -> None:
    # Given: log market value is both a model feature and the size exposure control.
    preprocessor = FoldPreprocessor(("factor_a", "log_total_mv"), "log_total_mv")
    artifact = preprocessor.fit(_training_frame(), "fold_000", DATASET_ID)

    # When: the training cross-sections are transformed.
    transformed = preprocessor.transform(_training_frame(), artifact)

    # Then: size remains informative and its self-neutralization coefficient is disabled.
    size_statistics = artifact.feature_statistics[1]
    assert size_statistics.neutralization_slope == 0.0
    assert transformed["log_total_mv"].abs().sum() > 0


def test_preprocessing_artifact_store_rejects_tampered_manifest(tmp_path: Path) -> None:
    # Given: persisted fold parameters whose bytes are modified after publication.
    artifact = FoldPreprocessor(("factor_a",), "log_total_mv").fit(
        _training_frame(),
        "fold_000",
        DATASET_ID,
    )
    store = FoldPreprocessorStore(tmp_path)
    descriptor = store.write(artifact)
    descriptor.manifest_path.write_text("{}", encoding="utf-8")

    # When / Then: altered preprocessing evidence fails closed on read.
    with pytest.raises(FoldPreprocessorStoreError, match="invalid"):
        store.read(descriptor)


def test_preprocessing_schema_documents_every_manifest_field() -> None:
    # Given: the committed machine-readable preprocessing schema.
    schema_path = ROOT / "schemas" / "fold_preprocessor_artifact_v1.json"

    # When: its required fields are compared with the Pydantic trust boundary.
    document = json.loads(schema_path.read_text(encoding="utf-8"))

    # Then: training cannot gain an undocumented manifest field.
    assert set(document["required"]) == set(FoldPreprocessingArtifact.model_fields)


def test_fold_preprocessor_rejects_duplicate_feature_contract() -> None:
    # Given: a feature order that aliases the same model column twice.
    # When / Then: the typed preprocessor cannot be constructed.
    with pytest.raises(FoldPreprocessingError, match="unique"):
        FoldPreprocessor(("factor_a", "factor_a"), "log_total_mv")


def test_fold_preprocessor_rejects_empty_training_fold() -> None:
    # Given: a typed frame with no training observations.
    preprocessor = FoldPreprocessor(("factor_a",), "log_total_mv")

    # When / Then: no fallback or fitted artifact is fabricated.
    with pytest.raises(FoldPreprocessingError, match="empty"):
        preprocessor.fit(_training_frame().head(0), "fold_000", DATASET_ID)


def test_fold_preprocessor_rejects_missing_feature_column() -> None:
    # Given: a training frame that omits one declared model feature.
    preprocessor = FoldPreprocessor(("factor_a",), "log_total_mv")

    # When / Then: the incomplete feature contract fails closed.
    with pytest.raises(FoldPreprocessingError, match="missing columns"):
        preprocessor.fit(_training_frame().drop("factor_a"), "fold_000", DATASET_ID)


def test_fold_transform_rejects_artifact_for_another_feature_contract() -> None:
    # Given: a valid fitted artifact relabeled with a different feature order.
    preprocessor = FoldPreprocessor(("factor_a",), "log_total_mv")
    artifact = preprocessor.fit(_training_frame(), "fold_000", DATASET_ID).model_copy(
        update={"feature_names": ("other_factor",)}
    )

    # When / Then: transform refuses parameters belonging to another contract.
    with pytest.raises(FoldPreprocessingError, match="differs"):
        preprocessor.transform(_validation_frame(), artifact)


def test_fold_fit_rejects_missing_size_exposure() -> None:
    # Given: every training value for the required size exposure is null.
    training = _training_frame().with_columns(pl.lit(None).cast(pl.Float64).alias("log_total_mv"))

    # When / Then: neutralization cannot silently proceed without size evidence.
    with pytest.raises(FoldPreprocessingError, match="training median"):
        FoldPreprocessor(("factor_a",), "log_total_mv").fit(
            training,
            "fold_000",
            DATASET_ID,
        )


def test_preprocessing_store_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: a valid descriptor whose path is relabeled outside its artifact directory.
    artifact = FoldPreprocessor(("factor_a",), "log_total_mv").fit(
        _training_frame(),
        "fold_000",
        DATASET_ID,
    )
    store = FoldPreprocessorStore(tmp_path)
    descriptor = store.write(artifact).model_copy(update={"manifest_path": tmp_path / "other.json"})

    # When / Then: the store enforces its physical kind boundary.
    with pytest.raises(FoldPreprocessorStoreError, match="boundary"):
        store.read(descriptor)


def test_preprocessing_manifest_rejects_statistics_in_wrong_feature_order() -> None:
    # Given: a two-feature artifact payload whose fitted statistics are reversed.
    artifact = FoldPreprocessor(("factor_a", "log_total_mv"), "log_total_mv").fit(
        _training_frame(),
        "fold_000",
        DATASET_ID,
    )
    payload = artifact.model_dump()
    payload["feature_statistics"] = tuple(reversed(artifact.feature_statistics))

    # When / Then: the artifact trust boundary rejects parameter-to-feature aliasing.
    with pytest.raises(ValidationError, match="feature_statistics"):
        FoldPreprocessingArtifact.model_validate(payload)
