from datetime import date

import pytest

from ashare_lab.research.datasets.spec import DatasetSpec, FeatureRef, LabelRef
from ashare_lab.services.factor_calendar_runtime import (
    FactorCalendarDocument,
    FactorCalendarRuntimeError,
    verified_development_calendar,
)


def _dataset_spec() -> DatasetSpec:
    return DatasetSpec(
        rulebook_version="1.1.0",
        coverage_report_id="coverage_abc123",
        input_manifest_id="inputs_abc123",
        source_snapshot_ids=("snap_calendar",),
        schema_manifest_id="schema_" + "a" * 64,
        input_schema_manifest_ids=("schema_" + "b" * 64,),
        lineage_manifest_id="lineage_abc123",
        feature_artifact_ids=("feature_artifact_abc123",),
        feature_lineage_edge_ids=("lineage_feature",),
        label_artifact_id="label_artifact_abc123",
        label_lineage_edge_ids=("lineage_label",),
        universe_version="universe_artifact_abc123",
        features=(FeatureRef(name="factor_a", version="1.0.0"),),
        label=LabelRef(name="label_a", version="1.0.0"),
        start_date=date(2020, 1, 1),
        end_date=date(2025, 12, 31),
    )


def _document(day: str, *, snapshot_id: str = "snap_calendar") -> FactorCalendarDocument:
    return FactorCalendarDocument(
        cal_date=day,
        is_open=1,
        quality_status="ACCEPTED",
        schema_manifest_id="schema_" + "b" * 64,
        source_snapshot_id=snapshot_id,
        source_row_sha256="c" * 64,
    )


def test_verified_calendar_folds_replays_and_excludes_final_holdout() -> None:
    # Given: duplicate immutable observations around the development boundary.
    documents = (
        _document("20200102"),
        _document("20200102"),
        _document("20241231"),
        _document("20250102"),
    )

    # When: the DatasetSpec-bound calendar is normalized.
    result = verified_development_calendar(
        documents,
        _dataset_spec(),
        "schema_" + "b" * 64,
    )

    # Then: stable replays collapse and the final holdout remains sealed.
    assert result == (date(2020, 1, 2), date(2024, 12, 31))


def test_verified_calendar_rejects_snapshot_outside_dataset_spec() -> None:
    # Given: an accepted calendar row sourced from an unbound Raw snapshot.
    documents = (_document("20200102", snapshot_id="snap_other"),)

    # When / Then: current database state cannot alter the frozen dataset split.
    with pytest.raises(FactorCalendarRuntimeError, match="outside DatasetSpec"):
        verified_development_calendar(
            documents,
            _dataset_spec(),
            "schema_" + "b" * 64,
        )


def test_verified_calendar_requires_dataset_bound_schema() -> None:
    # Given: a canonical schema that the DatasetSpec never qualified.
    documents = (_document("20200102"),)

    # When / Then: the runtime cannot substitute a newer schema.
    with pytest.raises(FactorCalendarRuntimeError, match="schema is absent"):
        verified_development_calendar(
            documents,
            _dataset_spec(),
            "schema_" + "d" * 64,
        )


def test_verified_calendar_rejects_nonaccepted_row() -> None:
    # Given: a calendar row that crossed the query boundary with failed quality.
    documents = (_document("20200102").model_copy(update={"quality_status": "REJECTED"}),)

    # When / Then: query predicates are rechecked after boundary parsing.
    with pytest.raises(FactorCalendarRuntimeError, match="quality boundary"):
        verified_development_calendar(
            documents,
            _dataset_spec(),
            "schema_" + "b" * 64,
        )


def test_verified_calendar_rejects_conflicting_replay() -> None:
    # Given: one natural date has two accepted but materially different states.
    documents = (
        _document("20200102"),
        _document("20200102").model_copy(update={"is_open": 0}),
    )

    # When / Then: neither replay is chosen silently.
    with pytest.raises(FactorCalendarRuntimeError, match="conflicting accepted facts"):
        verified_development_calendar(
            documents,
            _dataset_spec(),
            "schema_" + "b" * 64,
        )


def test_verified_calendar_rejects_empty_development_interval() -> None:
    # Given: no DatasetSpec-bound canonical session rows.
    documents: tuple[FactorCalendarDocument, ...] = ()

    # When / Then: the split cannot proceed from an empty calendar.
    with pytest.raises(FactorCalendarRuntimeError, match="calendar is empty"):
        verified_development_calendar(
            documents,
            _dataset_spec(),
            "schema_" + "b" * 64,
        )
