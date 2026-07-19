import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.research.experiments.trial_identity import TrialIdentityError
from ashare_lab.research.experiments.trial_ledger import (
    FactorTrial,
    TrialBatch,
    TrialBatchDescriptor,
    TrialLedgerError,
    TrialLedgerStore,
    TrialRegistrationContext,
    create_trial_batch,
)
from ashare_lab.research.factors.catalog import factor_hypotheses

DATASET_ID = "ds_862d155145b89879b679"
ROOT = Path(__file__).parents[1]


def _batch() -> TrialBatch:
    hypotheses = factor_hypotheses()
    artifact_ids = tuple(f"feature_artifact_{index:064x}" for index in range(len(hypotheses)))
    return create_trial_batch(
        context=TrialRegistrationContext(
            dataset_snapshot_id=DATASET_ID,
            rulebook_version="1.1.0",
            code_commit="a" * 40,
            registered_at=datetime(2026, 7, 19, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
            registered_by="research_owner",
        ),
        hypotheses=hypotheses,
        feature_artifact_ids=artifact_ids,
    )


def test_trial_ledger_registers_all_twenty_one_factors_before_results(tmp_path: Path) -> None:
    # Given: the fixed first-version hypothesis catalog and an empty immutable ledger.
    batch = _batch()
    store = TrialLedgerStore(tmp_path)

    # When: the complete research batch is registered.
    descriptor = store.write(batch)

    # Then: every DatasetSpec factor appears once and no result field exists in the ledger.
    restored = store.read(descriptor)
    assert len(restored.trials) == 21
    assert tuple(trial.feature_name for trial in restored.trials) == tuple(
        hypothesis.feature_name for hypothesis in factor_hypotheses()
    )
    assert all("result" not in type(trial).model_fields for trial in restored.trials)


def test_trial_ledger_is_idempotent_for_identical_batch(tmp_path: Path) -> None:
    # Given: one complete trial batch and its append-only store.
    batch = _batch()
    store = TrialLedgerStore(tmp_path)

    # When: identical registration is requested twice.
    first = store.write(batch)
    second = store.write(batch)

    # Then: the same immutable ledger identity is reused.
    assert first == second
    assert len(tuple((tmp_path / "trial_ledger").iterdir())) == 1


def test_trial_ledger_rejects_tampered_batch(tmp_path: Path) -> None:
    # Given: a persisted trial batch modified after append-only publication.
    store = TrialLedgerStore(tmp_path)
    descriptor = store.write(_batch())
    descriptor.manifest_path.write_text("{}", encoding="utf-8")

    # When / Then: diagnostics cannot proceed from altered registration evidence.
    with pytest.raises(TrialLedgerError, match="invalid"):
        store.read(descriptor)


def test_trial_ledger_rejects_caller_relabelled_batch_identity(tmp_path: Path) -> None:
    # Given: valid trial content with a caller-substituted hash-shaped batch ID.
    relabelled = _batch().model_copy(update={"batch_id": "trial_batch_" + "f" * 64})

    # When / Then: the store recomputes identity before publishing any ledger bytes.
    with pytest.raises(TrialLedgerError, match="identity differs"):
        TrialLedgerStore(tmp_path).write(relabelled)


def test_trial_batch_schema_documents_every_registered_field() -> None:
    # Given: the committed machine-readable trial batch schema.
    document = json.loads(
        (ROOT / "schemas" / "factor_trial_batch_v1.json").read_text(encoding="utf-8")
    )

    # When: top-level and nested required fields are compared with trust boundaries.
    documented = (set(document["required"]), set(document["$defs"]["FactorTrial"]["required"]))

    # Then: registration cannot gain an undocumented reproducibility or hypothesis field.
    assert documented == (set(TrialBatch.model_fields), set(FactorTrial.model_fields))


def test_trial_factory_rejects_misaligned_hypotheses_and_artifacts() -> None:
    # Given: one hypothesis but no corresponding feature artifact.
    context = TrialRegistrationContext(
        dataset_snapshot_id=DATASET_ID,
        rulebook_version="1.1.0",
        code_commit="a" * 40,
        registered_at=datetime(2026, 7, 19, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
        registered_by="research_owner",
    )

    # When / Then: a partial attempt batch cannot be created.
    with pytest.raises(TrialIdentityError, match="aligned"):
        create_trial_batch(context, factor_hypotheses()[:1], ())


def test_trial_ledger_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: a valid batch descriptor relabeled to another path.
    store = TrialLedgerStore(tmp_path)
    descriptor = store.write(_batch())
    crossed = TrialBatchDescriptor(
        batch_id=descriptor.batch_id,
        manifest_path=tmp_path / "other.json",
        data_sha256=descriptor.data_sha256,
    )

    # When / Then: callers cannot read trial evidence outside the ledger boundary.
    with pytest.raises(TrialLedgerError, match="boundary"):
        store.read(crossed)
