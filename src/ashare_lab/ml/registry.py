"""Immutable model lifecycle transitions."""

from dataclasses import dataclass, replace
from enum import StrEnum, unique
from typing import NewType

from ashare_lab.research.model_governance import TrainingApproval

ModelId = NewType("ModelId", str)
TrainingRunId = NewType("TrainingRunId", str)
DatasetSnapshotId = NewType("DatasetSnapshotId", str)


@unique
class ModelStatus(StrEnum):
    """Governed lifecycle states for research models."""

    DRAFT = "draft"
    VALIDATED = "validated"
    REJECTED = "rejected"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class ModelRecord:
    """Registry metadata linking a model to data and training lineage."""

    model_id: ModelId
    dataset_snapshot_id: DatasetSnapshotId
    training_run_id: TrainingRunId
    status: ModelStatus
    approved_rulebook_version: str | None = None


class ModelPromotionError(Exception):
    """A model cannot make the requested governed lifecycle transition."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed model promotion failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the rejected lifecycle transition reason."""
        return self.detail


def promote_model(record: ModelRecord, approval: TrainingApproval) -> ModelRecord:
    """Promote a draft without mutating its original registry record."""
    if not approval.approved:
        detail = "model promotion requires an approved training protocol"
        raise ModelPromotionError(detail)
    match record.status:
        case ModelStatus.DRAFT:
            return replace(
                record,
                status=ModelStatus.VALIDATED,
                approved_rulebook_version=approval.rulebook_version,
            )
        case ModelStatus.VALIDATED:
            detail = "model is already validated"
        case ModelStatus.REJECTED:
            detail = "a rejected model cannot be promoted"
        case ModelStatus.RETIRED:
            detail = "a retired model cannot be promoted"
    raise ModelPromotionError(detail)
