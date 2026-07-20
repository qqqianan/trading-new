from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.model_evidence import TrainingDataKind
from ashare_lab.research.model_governance import (
    ApprovalScope,
    ModelGovernanceError,
    ModelPurpose,
    ModelTrainingGuard,
)
from ashare_lab.research.preprocessing.training_identity import training_frame_sha256
from ashare_lab.research.splits.final_holdout import (
    FinalHoldoutAccessLedger,
    HoldoutAccessRecord,
)

from .training_support import build_training_evidence, folds, training_frame


def test_development_training_requires_zero_final_test_runs(tmp_path: Path) -> None:
    # Given: a development experiment falsely claiming the final test already ran.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    experiment = experiment.model_copy(update={"final_test_runs": 1})

    # When / Then: development training cannot consume final-test access.
    with pytest.raises(ModelGovernanceError, match="sealed"):
        ModelTrainingGuard().approve_development(evidence, experiment, folds(), frame)


def test_synthetic_data_cannot_train_investment_decision_model(tmp_path: Path) -> None:
    # Given: structurally complete synthetic QA artifacts claiming investment use.
    frame = training_frame()
    evidence, experiment = build_training_evidence(
        tmp_path,
        frame,
        purpose=ModelPurpose.INVESTMENT_DECISION,
        data_kind=TrainingDataKind.SYNTHETIC_QA,
    )

    # When / Then: artifact completeness cannot make synthetic data investable.
    with pytest.raises(ModelGovernanceError, match="synthetic"):
        ModelTrainingGuard().approve_development(evidence, experiment, folds(), frame)


def test_existing_holdout_access_blocks_development_training(tmp_path: Path) -> None:
    # Given: an otherwise valid run whose final-holdout ledger is already consumed.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    FinalHoldoutAccessLedger(tmp_path).append_once(
        HoldoutAccessRecord(
            record_id="holdout_access_" + "e" * 64,
            holdout_spec_id=evidence.holdout_spec_id,
            protocol_id="protocol_" + "f" * 64,
            dataset_snapshot_id=experiment.dataset_snapshot_id,
            accessed_at=datetime(2026, 7, 20, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
            authorized_by="research_owner",
            purpose="single_final_evaluation",
        )
    )

    # When / Then: development cannot continue after the sealed result was viewed.
    with pytest.raises(ModelGovernanceError, match="already opened"):
        ModelTrainingGuard().approve_development(evidence, experiment, folds(), frame)


def test_verified_development_artifacts_receive_draft_training_scope(tmp_path: Path) -> None:
    # Given: verified development-only evidence and no holdout access.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)

    # When: the artifact-backed guard evaluates the run.
    decision = ModelTrainingGuard().approve_development(evidence, experiment, folds(), frame)

    # Then: approval permits DRAFT fitting only, not validation promotion.
    assert decision.approval.approved is True
    assert decision.approval.scope is ApprovalScope.DEVELOPMENT_TRAINING


def test_development_training_rejects_frame_hash_mismatch(tmp_path: Path) -> None:
    # Given: valid evidence relabeled with a different development frame identity.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    evidence = replace(evidence, development_data_sha256="f" * 64)

    # When / Then: fitting cannot start from bytes outside the approved evidence.
    with pytest.raises(ModelGovernanceError, match="training frame bytes differ"):
        ModelTrainingGuard().approve_development(evidence, experiment, folds(), frame)


def test_development_training_rejects_frame_crossing_final_holdout(tmp_path: Path) -> None:
    # Given: a frame whose identity is valid but whose decision clock enters 2025.
    original = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, original)
    frame = original.with_columns(pl.col("decision_time").dt.offset_by("2y").alias("decision_time"))
    evidence = replace(evidence, development_data_sha256=training_frame_sha256(frame))

    # When / Then: content addressing cannot authorize final-holdout observations.
    with pytest.raises(ModelGovernanceError, match="crosses development end"):
        ModelTrainingGuard().approve_development(evidence, experiment, folds(), frame)


def test_development_training_rejects_preprocessor_identity_mismatch(tmp_path: Path) -> None:
    # Given: an experiment that substitutes one fold preprocessor identity.
    frame = training_frame()
    evidence, experiment = build_training_evidence(tmp_path, frame)
    experiment = experiment.model_copy(
        update={"preprocessor_artifact_ids": ("preprocessor_replaced",)}
    )

    # When / Then: every fold must retain its exact verified preprocessor artifact.
    with pytest.raises(ModelGovernanceError, match="preprocessor identities differ"):
        ModelTrainingGuard().approve_development(evidence, experiment, folds(), frame)
