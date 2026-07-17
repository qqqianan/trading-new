from dataclasses import replace
from datetime import date

import pytest

from ashare_lab.research.datasets.assembly import (
    DatasetAssemblyError,
    DatasetAssemblyRequest,
    FeatureArtifactEvidence,
    LabelArtifactEvidence,
    assemble_dataset_spec,
)
from ashare_lab.research.datasets.coverage import (
    ComponentCoverage,
    CoverageRequest,
    DatasetComponent,
    DatasetCoverageReport,
    DatasetInputManifest,
    build_input_manifest,
    qualify_dataset,
)
from ashare_lab.research.datasets.spec import FeatureRef, LabelRef


def _qualified() -> tuple[DatasetCoverageReport, DatasetInputManifest]:
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2025, 12, 31),
        (DatasetComponent.MARKET_DAILY,),
    )
    component = ComponentCoverage(
        component=DatasetComponent.MARKET_DAILY,
        start_date=date(2020, 1, 2),
        end_date=date(2026, 6, 16),
        schema_manifest_ids=("schema_a1",),
        source_snapshot_ids=("snap_a1",),
        lineage_edge_ids=("lineage_a1",),
        quality_passed=True,
        point_in_time=True,
    )
    report = qualify_dataset(request, (component,))
    return report, build_input_manifest(report)


def test_dataset_assembly_binds_materialized_feature_and_label_lineage() -> None:
    # Given: qualified inputs plus physically separate feature and label artifacts.
    report, inputs = _qualified()
    features = (
        FeatureArtifactEvidence(
            FeatureRef(name="momentum_20d", version="v1"),
            "feature_snapshot_a1",
            ("lineage_feature_a1",),
        ),
    )
    label = LabelArtifactEvidence(
        LabelRef(name="excess_open_to_open_20d", version="v1"),
        "label_snapshot_a1",
        ("lineage_label_a1",),
    )

    # When: the final logical dataset specification is assembled.
    spec = assemble_dataset_spec(
        report,
        inputs,
        features,
        label,
        DatasetAssemblyRequest(
            "ashare-pit-v1",
            date(2020, 1, 2),
            date(2025, 12, 31),
        ),
    )

    # Then: coverage and all original schema identities participate in ds identity.
    assert spec.coverage_report_id == report.report_id
    assert spec.input_manifest_id == inputs.manifest_id
    assert spec.input_schema_manifest_ids == inputs.input_schema_manifest_ids
    assert spec.snapshot_id.startswith("ds_")


def test_dataset_assembly_rejects_label_without_independent_lineage() -> None:
    # Given: qualified inputs but a label artifact with no output lineage.
    report, inputs = _qualified()
    feature = FeatureArtifactEvidence(
        FeatureRef(name="momentum_20d", version="v1"),
        "feature_snapshot_a1",
        ("lineage_feature_a1",),
    )
    label = LabelArtifactEvidence(
        LabelRef(name="excess_open_to_open_20d", version="v1"),
        "label_snapshot_a1",
        (),
    )

    # When / Then: input coverage cannot substitute for label lineage.
    with pytest.raises(DatasetAssemblyError, match="label lineage"):
        assemble_dataset_spec(
            report,
            inputs,
            (feature,),
            label,
            DatasetAssemblyRequest(
                "ashare-pit-v1",
                date(2020, 1, 2),
                date(2025, 12, 31),
            ),
        )


def test_dataset_assembly_rejects_input_manifest_from_another_report() -> None:
    # Given: valid artifacts but an input manifest bound to another coverage report.
    report, inputs = _qualified()
    mismatched = replace(inputs, coverage_report_id="coverage_deadbeef")
    feature = FeatureArtifactEvidence(
        FeatureRef(name="momentum_20d", version="v1"),
        "feature_snapshot_a1",
        ("lineage_feature_a1",),
    )
    label = LabelArtifactEvidence(
        LabelRef(name="excess_open_to_open_20d", version="v1"),
        "label_snapshot_a1",
        ("lineage_label_a1",),
    )

    # When / Then: cross-report evidence substitution is rejected.
    with pytest.raises(DatasetAssemblyError, match="does not belong"):
        assemble_dataset_spec(
            report,
            mismatched,
            (feature,),
            label,
            DatasetAssemblyRequest(
                "ashare-pit-v1",
                date(2020, 1, 2),
                date(2025, 12, 31),
            ),
        )


def test_dataset_assembly_rejects_missing_feature_artifacts() -> None:
    # Given: qualified inputs and a labeled target but no feature materialization.
    report, inputs = _qualified()
    label = LabelArtifactEvidence(
        LabelRef(name="excess_open_to_open_20d", version="v1"),
        "label_snapshot_a1",
        ("lineage_label_a1",),
    )

    # When / Then: a target-only dataset cannot be assembled.
    with pytest.raises(DatasetAssemblyError, match="no materialized feature"):
        assemble_dataset_spec(
            report,
            inputs,
            (),
            label,
            DatasetAssemblyRequest(
                "ashare-pit-v1",
                date(2020, 1, 2),
                date(2025, 12, 31),
            ),
        )
