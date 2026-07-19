"""Immutable models persisted by the factor trial ledger."""

from datetime import datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ashare_lab.research.factors.models import ExpectedDirection, FactorFamily


class FrozenTrialModel(BaseModel):
    """Immutable model persisted in the trial ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FactorTrial(FrozenTrialModel):
    """One attempt declared without any diagnostic result fields."""

    trial_id: str = Field(pattern=r"^factor_trial_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    feature_name: str = Field(min_length=1)
    feature_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    feature_artifact_id: str = Field(pattern=r"^feature_artifact_[0-9a-f]{64}$")
    family: FactorFamily
    expected_direction: ExpectedDirection
    simplicity_rank: int = Field(ge=0)
    diagnostic_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class TrialBatch(FrozenTrialModel):
    """Complete set of attempts atomically registered for one research batch."""

    batch_id: str = Field(pattern=r"^trial_batch_[0-9a-f]{64}$")
    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    rulebook_version: str = Field(min_length=1)
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    registered_at: datetime
    registered_by: str = Field(min_length=1)
    trials: tuple[FactorTrial, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def trials_are_unique_and_dataset_bound(self) -> Self:
        """Reject partial aliases and cross-dataset trial registration."""
        names = tuple(item.feature_name for item in self.trials)
        identities = tuple(item.trial_id for item in self.trials)
        if len(names) != len(set(names)) or len(identities) != len(set(identities)):
            detail = "trial feature names and identities must be unique"
            raise ValueError(detail)
        if any(item.dataset_snapshot_id != self.dataset_snapshot_id for item in self.trials):
            detail = "every trial must bind the batch DatasetSpec"
            raise ValueError(detail)
        return self


class TrialBatchDescriptor(FrozenTrialModel):
    """Verified path and byte identity for one append-only trial batch."""

    batch_id: str = Field(pattern=r"^trial_batch_[0-9a-f]{64}$")
    manifest_path: Path
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
