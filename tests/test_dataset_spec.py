from datetime import date

from ashare_lab.research.datasets.spec import DatasetSpec, FeatureRef, LabelRef


def _spec(
    label_version: str = "v1",
    lineage_manifest_id: str = "lineage_91a9c1",
    coverage_report_id: str = "coverage_a81c0f",
) -> DatasetSpec:
    return DatasetSpec(
        rulebook_version="1.1.0",
        coverage_report_id=coverage_report_id,
        input_manifest_id="inputs_84c2aa",
        source_snapshot_ids=("bars-2026-07-14", "fundamentals-2026q1"),
        schema_manifest_id="schema_36e2af",
        input_schema_manifest_ids=("schema_12ab", "schema_34cd"),
        lineage_manifest_id=lineage_manifest_id,
        feature_artifact_ids=("feature_a1", "feature_b2"),
        feature_lineage_edge_ids=("lineage_feature_a1", "lineage_feature_b2"),
        label_artifact_id="label_a1",
        label_lineage_edge_ids=("lineage_label_a1",),
        universe_version="csi-all-pit-v1",
        features=(
            FeatureRef(name="momentum_20d", version="v1"),
            FeatureRef(name="quality_roe", version="v2"),
        ),
        label=LabelRef(name="excess_open_to_open_20d", version=label_version),
        start_date=date(2018, 1, 1),
        end_date=date(2025, 12, 31),
    )


def test_dataset_fingerprint_is_stable_for_identical_inputs() -> None:
    # Given: two independently parsed but identical dataset specifications.
    first = _spec()
    second = _spec()

    # When / Then: content identity is deterministic and order-preserving.
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_id.startswith("ds_")


def test_dataset_fingerprint_changes_when_label_version_changes() -> None:
    # Given: specifications that differ only in their future-return definition.
    first = _spec("v1")
    second = _spec("v2")

    # When / Then: the datasets cannot silently share an identity.
    assert first.snapshot_id != second.snapshot_id


def test_dataset_fingerprint_changes_when_lineage_changes() -> None:
    # Given: the same logical features derived through different lineage manifests.
    first = _spec(lineage_manifest_id="lineage_91a9c1")
    second = _spec(lineage_manifest_id="lineage_f4410b")

    # When / Then: materially different derivations cannot share an identity.
    assert first.snapshot_id != second.snapshot_id


def test_dataset_fingerprint_changes_when_coverage_report_changes() -> None:
    # Given: identical logical features qualified by different coverage evidence.
    first = _spec(coverage_report_id="coverage_a81c0f")
    second = _spec(coverage_report_id="coverage_62d491")

    # When / Then: a new cross-table qualification creates a new dataset identity.
    assert first.snapshot_id != second.snapshot_id
