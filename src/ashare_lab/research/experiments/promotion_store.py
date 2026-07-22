"""Content-addressed persistence for development promotion evaluations."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ashare_lab.research.experiments.promotion_models import ModelPromotionEvaluation


class PromotionEvaluationDescriptor(BaseModel):
    """Verified reference to one immutable promotion evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str = Field(pattern=r"^model_promotion_[0-9a-f]{64}$")
    report_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PromotionEvaluationStoreError(Exception):
    """Promotion evidence is missing, altered, or outside its artifact boundary."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create one stable store failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the artifact boundary and concrete failure."""
        return f"promotion_evaluation_store: {self.detail}"


class PromotionEvaluationStore:
    """Publish immutable promotion decisions without overwriting evidence."""

    def __init__(self, root: Path) -> None:
        """Bind the store to one caller-owned artifact root."""
        self._root = root / "model_promotions"

    def write(self, evaluation: ModelPromotionEvaluation) -> PromotionEvaluationDescriptor:
        """Atomically publish or verify one complete evaluation."""
        content = f"{evaluation.model_dump_json(indent=2)}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        evaluation_id = f"model_promotion_{digest}"
        directory = self._root / evaluation_id
        descriptor = PromotionEvaluationDescriptor(
            evaluation_id=evaluation_id,
            report_path=directory / "report.json",
            data_sha256=digest,
        )
        if directory.exists():
            if self.read(descriptor) != evaluation:
                detail = "existing promotion evaluation content differs"
                raise PromotionEvaluationStoreError(detail)
            return descriptor
        self._root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".tmp-", dir=self._root) as temporary_name:
            temporary = Path(temporary_name)
            (temporary / "report.json").write_bytes(content)
            temporary.replace(directory)
        return descriptor

    def read(self, descriptor: PromotionEvaluationDescriptor) -> ModelPromotionEvaluation:
        """Verify exact path, bytes, identity, and complete report schema."""
        expected = self._root / descriptor.evaluation_id / "report.json"
        if descriptor.report_path != expected:
            detail = "descriptor crosses promotion evaluation boundary"
            raise PromotionEvaluationStoreError(detail)
        try:
            content = descriptor.report_path.read_bytes()
            evaluation = ModelPromotionEvaluation.model_validate_json(content)
        except (OSError, ValidationError) as error:
            detail = "promotion evaluation is missing or invalid"
            raise PromotionEvaluationStoreError(detail) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.data_sha256 or descriptor.evaluation_id != (
            f"model_promotion_{digest}"
        ):
            detail = "promotion evaluation bytes differ from descriptor"
            raise PromotionEvaluationStoreError(detail)
        return evaluation
