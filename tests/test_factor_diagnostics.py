import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ashare_lab.research.experiments.trial_ledger import (
    FactorTrial,
    TrialBatch,
    TrialLedgerStore,
    TrialRegistrationContext,
    create_trial_batch,
)
from ashare_lab.research.factors.catalog import factor_hypotheses
from ashare_lab.research.factors.contracts import FactorDiagnosticInput
from ashare_lab.research.factors.diagnostics import (
    DiagnosticConfig,
    FactorDiagnosticError,
    diagnose_factor,
)
from ashare_lab.research.factors.models import (
    ExpectedDirection,
    FactorDiagnosticReport,
    SegmentMetric,
)
from ashare_lab.research.factors.report_store import (
    FactorReportDescriptor,
    FactorReportStore,
    FactorReportStoreError,
)
from ashare_lab.research.factors.selection import (
    FactorDecision,
    FactorDecisionReason,
    FactorDecisionStatus,
    FactorResearchReport,
    FactorSelectionError,
)
from ashare_lab.research.factors.service import AuditedFactorResearchService

DATASET_ID = "ds_862d155145b89879b679"
ROOT = Path(__file__).parents[1]


def _registration_context() -> TrialRegistrationContext:
    return TrialRegistrationContext(
        dataset_snapshot_id=DATASET_ID,
        rulebook_version="1.1.0",
        code_commit="a" * 40,
        registered_at=datetime(2026, 7, 19, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
        registered_by="research_owner",
    )


def _reversal_trial() -> FactorTrial:
    hypothesis = next(item for item in factor_hypotheses() if item.feature_name == "reversal_5")
    batch = create_trial_batch(
        context=_registration_context(),
        hypotheses=(hypothesis,),
        feature_artifact_ids=("feature_artifact_" + "a" * 64,),
    )
    return batch.trials[0]


def _diagnostic_frame() -> pl.DataFrame:
    timezone = ZoneInfo("Asia/Shanghai")
    rows: list[dict[str, str | float | datetime | None]] = []
    dates = (
        datetime(2023, 12, 22, 18, tzinfo=timezone),
        datetime(2023, 12, 29, 18, tzinfo=timezone),
        datetime(2024, 1, 5, 18, tzinfo=timezone),
        datetime(2024, 1, 12, 18, tzinfo=timezone),
    )
    for date_index, decision_time in enumerate(dates):
        for symbol_index in range(10):
            factor = float(symbol_index)
            label = -factor / 100 + (0.001 if date_index % 2 == 0 else -0.001)
            rows.append(
                {
                    "decision_time": decision_time,
                    "symbol": f"0000{symbol_index:02d}.SZ",
                    "factor_value": None if date_index == 0 and symbol_index == 0 else factor,
                    "label_value": label,
                    "log_total_mv": float(symbol_index + 10),
                    "industry": "BANK" if symbol_index < 5 else "TECH",
                    "market_regime": "BULL" if date_index < 2 else "BEAR",
                }
            )
    return pl.DataFrame(rows)


def _full_batch() -> TrialBatch:
    hypotheses = factor_hypotheses()
    return create_trial_batch(
        context=_registration_context(),
        hypotheses=hypotheses,
        feature_artifact_ids=tuple(
            f"feature_artifact_{index:064x}" for index in range(len(hypotheses))
        ),
    )


def test_reversal_diagnostic_records_direction_flip_and_complete_segments() -> None:
    # Given: a registered lower-is-better reversal trial and development-only observations.
    trial = _reversal_trial()

    # When: the factor is diagnosed under the frozen metric configuration.
    report = diagnose_factor(_diagnostic_frame(), trial, DiagnosticConfig())

    # Then: raw negative IC becomes positive after the predeclared direction flip.
    assert report.expected_direction is ExpectedDirection.LOWER_IS_BETTER
    assert report.raw_mean_rank_ic < 0
    assert report.oriented_mean_rank_ic > 0
    assert report.missing_feature_count == 1
    assert report.worst_year is not None
    assert report.worst_industry is not None
    assert {item.segment for item in report.regime_segments} == {"BEAR", "BULL"}
    assert len(report.quintile_mean_labels) == 5


def test_diagnostic_rejects_final_holdout_rows() -> None:
    # Given: one registered trial and a frame containing a 2025 observation.
    frame = _diagnostic_frame().with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(datetime(2025, 1, 3, 18, tzinfo=ZoneInfo("Asia/Shanghai")))
        .otherwise(pl.col("decision_time"))
        .alias("decision_time")
    )

    # When / Then: factor research cannot silently inspect the final holdout.
    with pytest.raises(FactorDiagnosticError, match="final holdout"):
        diagnose_factor(frame, _reversal_trial(), DiagnosticConfig())


def test_audited_report_keeps_redundant_factor_with_stable_rejection(tmp_path: Path) -> None:
    # Given: two registered same-family momentum trials with identical development values.
    hypotheses = factor_hypotheses()[:2]
    batch = create_trial_batch(
        context=_registration_context(),
        hypotheses=hypotheses,
        feature_artifact_ids=(
            "feature_artifact_" + "a" * 64,
            "feature_artifact_" + "b" * 64,
        ),
    )
    store = TrialLedgerStore(tmp_path)
    descriptor = store.write(batch)
    positive_frame = _diagnostic_frame().with_columns((-pl.col("label_value")).alias("label_value"))
    inputs = tuple(
        FactorDiagnosticInput(trial_id=trial.trial_id, frame=positive_frame)
        for trial in batch.trials
    )

    # When: the service verifies registration, diagnoses, corrects FDR, and de-duplicates.
    report = AuditedFactorResearchService(store).run(descriptor, inputs)

    # Then: the simpler factor survives and the redundant trial remains visible as rejected.
    assert tuple(item.status for item in report.decisions) == (
        FactorDecisionStatus.CANDIDATE,
        FactorDecisionStatus.REJECTED,
    )
    assert report.decisions[1].reasons == (FactorDecisionReason.REDUNDANT_HIGH_CORRELATION,)
    assert len(report.diagnostics) == len(report.decisions) == 2


def test_audited_service_rejects_unregistered_partial_inputs(tmp_path: Path) -> None:
    # Given: a two-trial ledger batch but only one diagnostic input.
    hypotheses = factor_hypotheses()[:2]
    batch = create_trial_batch(
        context=_registration_context(),
        hypotheses=hypotheses,
        feature_artifact_ids=(
            "feature_artifact_" + "a" * 64,
            "feature_artifact_" + "b" * 64,
        ),
    )
    store = TrialLedgerStore(tmp_path)
    descriptor = store.write(batch)
    partial = (FactorDiagnosticInput(batch.trials[0].trial_id, _diagnostic_frame()),)

    # When / Then: calculation cannot begin with an undisclosed or omitted attempt.
    with pytest.raises(FactorSelectionError, match="exact order"):
        AuditedFactorResearchService(store).run(descriptor, partial)


def test_audited_report_retains_all_twenty_one_registered_trials(tmp_path: Path) -> None:
    # Given: the complete DatasetSpec hypothesis closure is registered before calculation.
    batch = _full_batch()
    ledger = TrialLedgerStore(tmp_path)
    descriptor = ledger.write(batch)
    positive_frame = _diagnostic_frame().with_columns((-pl.col("label_value")).alias("label_value"))
    inputs = tuple(
        FactorDiagnosticInput(trial_id=item.trial_id, frame=positive_frame) for item in batch.trials
    )

    # When: the full batch is diagnosed and selected.
    report = AuditedFactorResearchService(ledger).run(descriptor, inputs)

    # Then: no losing, missing, or redundant factor is omitted from the report.
    expected = tuple(item.feature_name for item in factor_hypotheses())
    assert tuple(item.feature_name for item in report.decisions) == expected
    assert len(report.diagnostics) == len(report.decisions) == 21
    assert any(item.status is FactorDecisionStatus.REJECTED for item in report.decisions)


def test_factor_report_store_is_content_addressed(tmp_path: Path) -> None:
    # Given: one complete audited report and its immutable artifact store.
    batch = _full_batch()
    ledger = TrialLedgerStore(tmp_path)
    descriptor = ledger.write(batch)
    positive_frame = _diagnostic_frame().with_columns((-pl.col("label_value")).alias("label_value"))
    report = AuditedFactorResearchService(ledger).run(
        descriptor,
        tuple(
            FactorDiagnosticInput(trial_id=item.trial_id, frame=positive_frame)
            for item in batch.trials
        ),
    )
    store = FactorReportStore(tmp_path)

    # When: identical complete report content is published twice.
    first = store.write(report)
    second = store.write(report)

    # Then: one stable identity is reused and verifies on read.
    assert first == second
    assert first.report_id.startswith("factor_report_")
    assert store.read(first) == report


def test_factor_report_schema_documents_all_nested_fields() -> None:
    # Given: the committed complete factor research report schema.
    document = json.loads(
        (ROOT / "schemas" / "factor_research_report_v1.json").read_text(encoding="utf-8")
    )
    definitions = document["$defs"]

    # When: every required field set is compared with its Pydantic trust boundary.
    documented = (
        set(document["required"]),
        set(definitions["FactorDiagnosticReport"]["required"]),
        set(definitions["FactorDecision"]["required"]),
        set(definitions["SegmentMetric"]["required"]),
    )

    # Then: reports cannot silently add undocumented metrics or omit rejection evidence.
    assert documented == (
        set(FactorResearchReport.model_fields),
        set(FactorDiagnosticReport.model_fields),
        set(FactorDecision.model_fields),
        set(SegmentMetric.model_fields),
    )


def test_diagnostic_rejects_missing_required_column() -> None:
    # Given: a registered factor frame without point-in-time size evidence.
    frame = _diagnostic_frame().drop("log_total_mv")

    # When / Then: incomplete diagnostics cannot be calculated.
    with pytest.raises(FactorDiagnosticError, match="missing columns"):
        diagnose_factor(frame, _reversal_trial(), DiagnosticConfig())


def test_diagnostic_rejects_all_missing_feature_values() -> None:
    # Given: a registered trial whose complete development feature is missing.
    frame = _diagnostic_frame().with_columns(pl.lit(None).cast(pl.Float64).alias("factor_value"))

    # When / Then: no IC or candidate evidence is fabricated.
    with pytest.raises(FactorDiagnosticError, match="no finite"):
        diagnose_factor(frame, _reversal_trial(), DiagnosticConfig())


def test_diagnostic_rejects_dates_below_minimum_pair_count() -> None:
    # Given: every date has fewer observations than the frozen diagnostic minimum.
    config = DiagnosticConfig(minimum_pairs_per_date=11)

    # When / Then: underpowered dates cannot be presented as valid diagnostics.
    with pytest.raises(FactorDiagnosticError, match="enough finite pairs"):
        diagnose_factor(_diagnostic_frame(), _reversal_trial(), config)


def test_factor_report_store_rejects_cross_boundary_descriptor(tmp_path: Path) -> None:
    # Given: a valid report descriptor whose path is relabeled outside its directory.
    batch = _full_batch()
    ledger = TrialLedgerStore(tmp_path)
    batch_descriptor = ledger.write(batch)
    frame = _diagnostic_frame().with_columns((-pl.col("label_value")).alias("label_value"))
    report = AuditedFactorResearchService(ledger).run(
        batch_descriptor,
        tuple(FactorDiagnosticInput(item.trial_id, frame) for item in batch.trials),
    )
    store = FactorReportStore(tmp_path)
    descriptor = store.write(report)
    crossed = FactorReportDescriptor(
        report_id=descriptor.report_id,
        report_path=tmp_path / "other.json",
        data_sha256=descriptor.data_sha256,
    )

    # When / Then: factor reports cannot be read through an arbitrary path.
    with pytest.raises(FactorReportStoreError, match="boundary"):
        store.read(crossed)


def test_factor_report_store_rejects_tampered_report(tmp_path: Path) -> None:
    # Given: one report whose persisted JSON is modified after publication.
    batch = _full_batch()
    ledger = TrialLedgerStore(tmp_path)
    batch_descriptor = ledger.write(batch)
    frame = _diagnostic_frame().with_columns((-pl.col("label_value")).alias("label_value"))
    report = AuditedFactorResearchService(ledger).run(
        batch_descriptor,
        tuple(FactorDiagnosticInput(item.trial_id, frame) for item in batch.trials),
    )
    store = FactorReportStore(tmp_path)
    descriptor = store.write(report)
    descriptor.report_path.write_text("{}", encoding="utf-8")

    # When / Then: diagnostics fail closed on altered report evidence.
    with pytest.raises(FactorReportStoreError, match="invalid"):
        store.read(descriptor)
