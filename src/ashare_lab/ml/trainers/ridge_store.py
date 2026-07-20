"""Atomic content-addressed storage for Ridge JSON artifacts."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from ashare_lab.ml.contracts import ModelArtifact
from ashare_lab.ml.trainers.ridge_models import (
    RidgeArtifactPayload,
    RidgeExperimentArtifact,
    RidgePredictionArtifact,
)


class RidgeArtifactStoreError(Exception):
    """A Ridge manifest or prediction artifact is missing or altered."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed Ridge storage failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the Ridge boundary and concrete failure."""
        return f"ridge_artifact: {self.detail}"


class RidgeArtifactStore:
    """Publish model coefficients and predictions without unsafe pickle files."""

    def __init__(self, artifact_root: Path) -> None:
        """Bind the model store to one caller-owned artifact root."""
        self._root = artifact_root / "models" / "ridge"

    def write(
        self,
        payload: RidgeArtifactPayload,
        predictions: RidgePredictionArtifact,
    ) -> ModelArtifact:
        """Atomically persist and return a generic content-addressed model reference."""
        prediction_content = f"{predictions.model_dump_json()}\n".encode()
        if hashlib.sha256(prediction_content).hexdigest() != payload.prediction_artifact_sha256:
            detail = "prediction bytes differ from Ridge payload"
            raise RidgeArtifactStoreError(detail)
        payload_json = json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        model_id = f"ridge_model_{hashlib.sha256(payload_json).hexdigest()}"
        artifact = RidgeExperimentArtifact(model_id=model_id, **payload.model_dump())
        manifest_content = f"{artifact.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(manifest_content).hexdigest()
        directory = self._root / model_id
        descriptor = ModelArtifact(
            model_id,
            payload.training_run_id,
            payload.dataset_snapshot_id,
            str(directory / "manifest.json"),
            digest,
        )
        if directory.exists():
            if self.read(descriptor) != artifact:
                detail = "existing Ridge artifact differs"
                raise RidgeArtifactStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "manifest.json").write_bytes(manifest_content)
            (temporary / "predictions.json").write_bytes(prediction_content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: ModelArtifact) -> RidgeExperimentArtifact:
        """Verify model path, manifest bytes, identity, and prediction bytes."""
        directory = self._root / descriptor.model_id
        expected = directory / "manifest.json"
        if Path(descriptor.artifact_uri) != expected:
            detail = "descriptor crosses Ridge artifact boundary"
            raise RidgeArtifactStoreError(detail)
        try:
            content = expected.read_bytes()
            artifact = RidgeExperimentArtifact.model_validate_json(content)
            prediction_content = (directory / "predictions.json").read_bytes()
            RidgePredictionArtifact.model_validate_json(prediction_content)
        except (OSError, ValidationError) as error:
            detail = "Ridge artifact is missing or invalid"
            raise RidgeArtifactStoreError(detail) from error
        if (
            hashlib.sha256(content).hexdigest() != descriptor.artifact_sha256
            or artifact.model_id != descriptor.model_id
            or hashlib.sha256(prediction_content).hexdigest() != artifact.prediction_artifact_sha256
        ):
            detail = "Ridge artifact bytes differ from descriptor"
            raise RidgeArtifactStoreError(detail)
        return artifact

    def descriptor(self, model_id: str) -> ModelArtifact:
        """Create a verified descriptor from one fixed Ridge model directory."""
        path = self._root / model_id / "manifest.json"
        try:
            content = path.read_bytes()
            artifact = RidgeExperimentArtifact.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "Ridge model manifest is missing or invalid"
            raise RidgeArtifactStoreError(detail) from error
        descriptor = ModelArtifact(
            model_id=artifact.model_id,
            training_run_id=artifact.training_run_id,
            dataset_snapshot_id=artifact.dataset_snapshot_id,
            artifact_uri=str(path),
            artifact_sha256=hashlib.sha256(content).hexdigest(),
        )
        self.read(descriptor)
        return descriptor

    def read_predictions(self, descriptor: ModelArtifact) -> RidgePredictionArtifact:
        """Verify the model envelope, then return its exact internal-test predictions."""
        artifact = self.read(descriptor)
        path = self._root / descriptor.model_id / "predictions.json"
        try:
            content = path.read_bytes()
            predictions = RidgePredictionArtifact.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "Ridge prediction artifact is missing or invalid"
            raise RidgeArtifactStoreError(detail) from error
        if hashlib.sha256(content).hexdigest() != artifact.prediction_artifact_sha256:
            detail = "Ridge prediction bytes differ from model manifest"
            raise RidgeArtifactStoreError(detail)
        return predictions
