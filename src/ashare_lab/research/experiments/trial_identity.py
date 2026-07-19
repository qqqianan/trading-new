"""Content identities and factory for preregistered factor trials."""

import hashlib
import json
from datetime import datetime

from pydantic import Field

from ashare_lab.research.experiments.trial_models import (
    FactorTrial,
    FrozenTrialModel,
    TrialBatch,
)
from ashare_lab.research.factors.models import FactorHypothesis


class TrialRegistrationContext(FrozenTrialModel):
    """Reproducibility evidence shared by every trial in one batch."""

    dataset_snapshot_id: str = Field(pattern=r"^ds_[0-9a-f]+$")
    rulebook_version: str = Field(min_length=1)
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    registered_at: datetime
    registered_by: str = Field(min_length=1)


def create_trial_batch(
    context: TrialRegistrationContext,
    hypotheses: tuple[FactorHypothesis, ...],
    feature_artifact_ids: tuple[str, ...],
) -> TrialBatch:
    """Create stable trial identities before labels or results are inspected."""
    if len(hypotheses) != len(feature_artifact_ids) or not hypotheses:
        detail = "hypotheses and feature artifacts must be non-empty and aligned"
        raise TrialIdentityError(detail)
    trials = tuple(
        _create_trial(context.dataset_snapshot_id, hypothesis, artifact_id)
        for hypothesis, artifact_id in zip(hypotheses, feature_artifact_ids, strict=True)
    )
    return TrialBatch(
        batch_id=_batch_id(context, trials),
        dataset_snapshot_id=context.dataset_snapshot_id,
        rulebook_version=context.rulebook_version,
        code_commit=context.code_commit,
        registered_at=context.registered_at,
        registered_by=context.registered_by,
        trials=trials,
    )


def validate_trial_identities(batch: TrialBatch) -> None:
    """Recompute every caller-controlled content identity and fail closed."""
    for trial in batch.trials:
        hypothesis = FactorHypothesis(
            feature_name=trial.feature_name,
            feature_version=trial.feature_version,
            family=trial.family,
            expected_direction=trial.expected_direction,
            simplicity_rank=trial.simplicity_rank,
        )
        if _create_trial(batch.dataset_snapshot_id, hypothesis, trial.feature_artifact_id) != trial:
            detail = f"trial identity differs for {trial.feature_name}"
            raise TrialIdentityError(detail)
    context = TrialRegistrationContext(
        dataset_snapshot_id=batch.dataset_snapshot_id,
        rulebook_version=batch.rulebook_version,
        code_commit=batch.code_commit,
        registered_at=batch.registered_at,
        registered_by=batch.registered_by,
    )
    if batch.batch_id != _batch_id(context, batch.trials):
        detail = "trial batch identity differs from registered content"
        raise TrialIdentityError(detail)


class TrialIdentityError(Exception):
    """A caller-controlled trial or batch ID differs from its content."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Create a typed trial identity failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the identity boundary and concrete failure."""
        return f"trial_identity: {self.detail}"


def _create_trial(
    dataset_snapshot_id: str,
    hypothesis: FactorHypothesis,
    artifact_id: str,
) -> FactorTrial:
    identity = "|".join(
        (
            dataset_snapshot_id,
            hypothesis.feature_name,
            hypothesis.feature_version,
            artifact_id,
            hypothesis.family.value,
            hypothesis.expected_direction.value,
            str(hypothesis.simplicity_rank),
            "1.0.0",
        )
    )
    return FactorTrial(
        trial_id=f"factor_trial_{hashlib.sha256(identity.encode()).hexdigest()}",
        dataset_snapshot_id=dataset_snapshot_id,
        feature_name=hypothesis.feature_name,
        feature_version=hypothesis.feature_version,
        feature_artifact_id=artifact_id,
        family=hypothesis.family,
        expected_direction=hypothesis.expected_direction,
        simplicity_rank=hypothesis.simplicity_rank,
        diagnostic_version="1.0.0",
    )


def _batch_id(context: TrialRegistrationContext, trials: tuple[FactorTrial, ...]) -> str:
    payload = json.dumps(
        {
            "dataset_snapshot_id": context.dataset_snapshot_id,
            "rulebook_version": context.rulebook_version,
            "code_commit": context.code_commit,
            "registered_at": context.registered_at.isoformat(),
            "registered_by": context.registered_by,
            "trial_ids": [item.trial_id for item in trials],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"trial_batch_{hashlib.sha256(payload).hexdigest()}"
