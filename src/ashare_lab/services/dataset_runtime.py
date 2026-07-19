"""Composition root for the first complete immutable DatasetSpec."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

from ashare_lab.code_identity import load_git_evidence
from ashare_lab.research.artifacts import ArtifactDescriptor
from ashare_lab.research.artifacts.artifact_identity import artifact_descriptor
from ashare_lab.research.artifacts.artifact_io import load_manifest
from ashare_lab.research.datasets.spec import FeatureRef, LabelRef
from ashare_lab.research.datasets.spec_store import DatasetSpecDescriptor, DatasetSpecStore
from ashare_lab.research.labels.catalog import medium_horizon_label
from ashare_lab.services.dataset_artifact_catalog import registered_feature_artifacts
from ashare_lab.services.dataset_coverage_runtime import qualify_default_dataset
from ashare_lab.services.dataset_publication import (
    DatasetPublicationError,
    DatasetPublicationRequest,
    MaterializedFeature,
    MaterializedLabel,
    publish_dataset_spec,
)

_UNIVERSE_ARTIFACT_ID: Final = (
    "universe_artifact_a5e618d3b4273bc97b8720bc8a31808fed91d00446cfb5e60a6f9cac6040de1b"
)


@dataclass(frozen=True, slots=True)
class DefaultDatasetRequest:
    """Label identity and closed source/dataset intervals for publication."""

    label: ArtifactDescriptor
    start_date: date
    end_date: date
    coverage_start_date: date
    coverage_end_date: date


def publish_default_dataset_spec(
    project_root: Path,
    request: DefaultDatasetRequest,
) -> DatasetSpecDescriptor:
    """Qualify current inputs and publish the fixed 21-feature logical dataset."""
    identity = load_git_evidence(project_root)
    if not identity.is_clean:
        detail = "dataset publication requires a clean Git worktree"
        raise DatasetPublicationError(detail)
    coverage = qualify_default_dataset(
        request.coverage_start_date,
        request.coverage_end_date,
        require_industry=False,
    )
    if coverage.manifest is None:
        detail = "qualified input manifest is absent"
        raise DatasetPublicationError(detail)
    artifact_root = project_root / "data" / "artifacts"
    universe = _load_artifact(artifact_root, "universe", _UNIVERSE_ARTIFACT_ID)
    universe_manifest = load_manifest(universe.manifest_path)
    features = tuple(
        _load_feature(
            artifact_root, registration.name, registration.version, registration.artifact_id
        )
        for registration in registered_feature_artifacts()
    )
    label_manifest = load_manifest(request.label.manifest_path)
    definition = medium_horizon_label()
    return publish_dataset_spec(
        DatasetSpecStore(artifact_root),
        DatasetPublicationRequest(
            report=coverage.report,
            inputs=coverage.manifest,
            universe=universe,
            universe_manifest=universe_manifest,
            features=features,
            label=MaterializedLabel(
                LabelRef(name=definition.name, version=definition.version),
                request.label,
                label_manifest,
            ),
            start_date=request.start_date,
            end_date=request.end_date,
        ),
    )


def _load_feature(
    artifact_root: Path,
    name: str,
    version: str,
    artifact_id: str,
) -> MaterializedFeature:
    descriptor = _load_artifact(artifact_root, "feature", artifact_id)
    manifest = load_manifest(descriptor.manifest_path)
    expected_names = {f"market_factor_{name}", f"financial_factor_{name}"}
    if manifest.transform_name not in expected_names:
        detail = f"registered feature transform mismatch: {artifact_id}"
        raise DatasetPublicationError(detail)
    return MaterializedFeature(FeatureRef(name=name, version=version), descriptor, manifest)


def _load_artifact(
    artifact_root: Path,
    kind: str,
    artifact_id: str,
) -> ArtifactDescriptor:
    directory = artifact_root / kind / artifact_id
    manifest = load_manifest(directory / "manifest.json")
    return artifact_descriptor(directory, manifest)
