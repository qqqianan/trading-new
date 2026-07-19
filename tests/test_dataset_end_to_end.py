from datetime import date
from pathlib import Path

import pytest

from ashare_lab.code_identity import GitEvidence
from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ArtifactKind,
)
from ashare_lab.research.artifacts.models import ArtifactManifest
from ashare_lab.research.datasets.coverage import (
    ComponentCoverage,
    CoverageRequest,
    DatasetComponent,
    DatasetCoverageReport,
    DatasetInputManifest,
    build_input_manifest,
    qualify_dataset,
)
from ashare_lab.research.datasets.spec import DatasetSpec, FeatureRef, LabelRef
from ashare_lab.research.datasets.spec_store import DatasetSpecStore, DatasetSpecStoreError
from ashare_lab.services import dataset_runtime
from ashare_lab.services.dataset_artifact_catalog import registered_feature_artifacts
from ashare_lab.services.dataset_publication import (
    DatasetPublicationError,
    DatasetPublicationRequest,
    MaterializedFeature,
    MaterializedLabel,
    publish_dataset_spec,
)
from ashare_lab.services.dataset_runtime import DefaultDatasetRequest


def test_dataset_spec_store_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    # Given: one complete logical dataset specification.
    store = DatasetSpecStore(tmp_path)
    spec = _spec()

    # When: identical governed inputs are published twice.
    first = store.write(spec)
    second = store.write(spec)

    # Then: one immutable ds identity and one exact JSON payload are reused.
    assert first == second
    assert first.snapshot_id == spec.snapshot_id
    assert store.read(first) == spec


def test_dataset_spec_store_rejects_tampered_existing_manifest(tmp_path: Path) -> None:
    # Given: a published DatasetSpec whose bytes are replaced after publication.
    store = DatasetSpecStore(tmp_path)
    descriptor = store.write(_spec())
    descriptor.manifest_path.write_text("{}", encoding="utf-8")

    # When / Then: replay refuses to bless the altered dataset identity.
    with pytest.raises(DatasetSpecStoreError, match="content_mismatch"):
        store.write(_spec())


def test_dataset_publication_binds_separate_artifacts_and_qualified_inputs(
    tmp_path: Path,
) -> None:
    # Given: qualified inputs and separate universe, feature, and label manifests.
    report, inputs = _qualified()
    universe = _artifact("universe_a1", ArtifactKind.UNIVERSE, 2)
    feature = _materialized_feature(inputs, universe)
    label = _materialized_label(inputs, universe)

    # When: the final logical DatasetSpec is assembled and published.
    descriptor = publish_dataset_spec(
        DatasetSpecStore(tmp_path),
        DatasetPublicationRequest(
            report=report,
            inputs=inputs,
            universe=universe,
            universe_manifest=_manifest(
                universe,
                inputs.manifest_id,
                inputs.lineage_manifest_id,
                "universe_panel",
            ),
            features=(feature,),
            label=label,
            start_date=date(2020, 1, 3),
            end_date=date(2025, 12, 31),
        ),
    )

    # Then: the immutable logical dataset is addressable without merging label columns.
    restored = DatasetSpecStore(tmp_path).read(descriptor)
    assert restored.feature_artifact_ids == (feature.descriptor.artifact_id,)
    assert restored.label_artifact_id == label.descriptor.artifact_id
    assert restored.universe_version == universe.artifact_id


def test_dataset_publication_rejects_artifact_from_another_input_manifest(
    tmp_path: Path,
) -> None:
    # Given: a feature claims a qualified closure different from the DatasetSpec input.
    report, inputs = _qualified()
    universe = _artifact("universe_a1", ArtifactKind.UNIVERSE, 2)
    feature = _materialized_feature(
        inputs,
        universe,
        input_id="inputs_alias",
    )
    label = _materialized_label(inputs, universe)
    request = DatasetPublicationRequest(
        report=report,
        inputs=inputs,
        universe=universe,
        universe_manifest=_manifest(
            universe,
            inputs.manifest_id,
            inputs.lineage_manifest_id,
            "universe_panel",
        ),
        features=(feature,),
        label=label,
        start_date=date(2020, 1, 3),
        end_date=date(2025, 12, 31),
    )

    # When / Then: content-addressed feature bytes cannot bypass upstream identity.
    with pytest.raises(DatasetPublicationError, match="upstream identity mismatch"):
        publish_dataset_spec(DatasetSpecStore(tmp_path), request)


def test_default_dataset_catalog_closes_exactly_twenty_one_features() -> None:
    # Given / When: the first governed artifact closure is loaded.
    registrations = registered_feature_artifacts()

    # Then: all planned features occur exactly once in deterministic order.
    assert len(registrations) == 21
    assert len({item.name for item in registrations}) == 21
    assert registrations[0].name == "mom_20"
    assert registrations[-1].name == "q_netprofit_yoy"


def test_dataset_runtime_rejects_dirty_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: local source differs from the committed artifact-producing code.
    def dirty_identity(_root: Path) -> GitEvidence:
        return GitEvidence("a" * 40, is_clean=False)

    monkeypatch.setattr(dataset_runtime, "load_git_evidence", dirty_identity)

    # When / Then: no coverage or artifact is read before the clean-code gate.
    with pytest.raises(DatasetPublicationError, match="clean Git worktree"):
        dataset_runtime.publish_default_dataset_spec(
            Path.cwd(),
            DefaultDatasetRequest(
                _artifact("label_a1", ArtifactKind.LABEL, 2),
                date(2020, 1, 3),
                date(2026, 7, 10),
                date(2020, 1, 2),
                date(2026, 7, 16),
            ),
        )


def _spec() -> DatasetSpec:
    return DatasetSpec(
        rulebook_version="1.1.0",
        coverage_report_id="coverage_a81c0f",
        input_manifest_id="inputs_84c2aa",
        source_snapshot_ids=("snap_market", "snap_benchmark"),
        schema_manifest_id="schema_36e2af",
        input_schema_manifest_ids=("schema_market", "schema_benchmark"),
        lineage_manifest_id="lineage_91a9c1",
        feature_artifact_ids=("feature_a1",),
        feature_lineage_edge_ids=("lineage_feature_a1",),
        label_artifact_id="label_a1",
        label_lineage_edge_ids=("lineage_label_a1",),
        universe_version="universe_a1",
        features=(FeatureRef(name="mom_20", version="1.0.0"),),
        label=LabelRef(name="relative_open_return_20d_csi500", version="1.0.0"),
        start_date=date(2020, 1, 3),
        end_date=date(2026, 7, 10),
    )


def _qualified() -> tuple[DatasetCoverageReport, DatasetInputManifest]:
    request = CoverageRequest(
        date(2020, 1, 2),
        date(2026, 7, 16),
        (DatasetComponent.MARKET_DAILY,),
    )
    component = ComponentCoverage(
        component=DatasetComponent.MARKET_DAILY,
        start_date=date(2020, 1, 2),
        end_date=date(2026, 7, 16),
        schema_manifest_ids=("schema_market",),
        source_snapshot_ids=("snap_market",),
        lineage_edge_ids=("lineage_market",),
        quality_passed=True,
        point_in_time=True,
    )
    report = qualify_dataset(request, (component,))
    return report, build_input_manifest(report)


def _artifact(identity: str, kind: ArtifactKind, rows: int) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=identity,
        kind=kind,
        schema_manifest_id="schema_a1",
        parquet_path=Path(f"/{kind.value}/{identity}/data.parquet"),
        manifest_path=Path(f"/{kind.value}/{identity}/manifest.json"),
        lineage_edge_id=f"lineage_{identity}",
        data_sha256="a" * 64,
        row_count=rows,
    )


def _manifest(
    artifact: ArtifactDescriptor,
    input_id: str,
    input_lineage: str,
    transform: str,
    *,
    universe_id: str | None = None,
) -> ArtifactManifest:
    upstreams = (input_id,) if universe_id is None else (input_id, universe_id)
    lineages = (
        (input_lineage,) if universe_id is None else (input_lineage, f"lineage_{universe_id}")
    )
    return ArtifactManifest(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        schema_manifest_id=artifact.schema_manifest_id,
        upstream_artifact_ids=upstreams,
        upstream_lineage_edge_ids=lineages,
        lineage_edge_id=artifact.lineage_edge_id,
        field_mappings=(),
        transform_name=transform,
        transform_version="1.0.0",
        parameters_sha256="b" * 64,
        code_commit="c" * 40,
        data_sha256=artifact.data_sha256,
        row_count=artifact.row_count,
        column_names=("symbol",),
    )


def _materialized_feature(
    inputs: DatasetInputManifest,
    universe: ArtifactDescriptor,
    *,
    input_id: str | None = None,
) -> MaterializedFeature:
    descriptor = _artifact("feature_a1", ArtifactKind.FEATURE, universe.row_count)
    return MaterializedFeature(
        FeatureRef(name="mom_20", version="1.0.0"),
        descriptor,
        _manifest(
            descriptor,
            inputs.manifest_id if input_id is None else input_id,
            inputs.lineage_manifest_id,
            "market_factor_mom_20",
            universe_id=universe.artifact_id,
        ),
    )


def _materialized_label(
    inputs: DatasetInputManifest,
    universe: ArtifactDescriptor,
) -> MaterializedLabel:
    descriptor = _artifact("label_a1", ArtifactKind.LABEL, universe.row_count)
    return MaterializedLabel(
        LabelRef(name="relative_open_return_20d_csi500", version="1.0.0"),
        descriptor,
        _manifest(
            descriptor,
            inputs.manifest_id,
            inputs.lineage_manifest_id,
            "relative_open_return_label",
            universe_id=universe.artifact_id,
        ),
    )
