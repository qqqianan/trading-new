"""Sole audited orchestration path from registered trials to factor decisions."""

from typing import Final, Protocol

import polars as pl

from ashare_lab.research.experiments.trial_ledger import (
    FactorTrial,
    TrialBatchDescriptor,
    TrialLedgerStore,
)
from ashare_lab.research.experiments.trial_models import TrialBatch
from ashare_lab.research.factors.contracts import FactorDiagnosticInput
from ashare_lab.research.factors.correlation import FactorCorrelation, same_family_correlations
from ashare_lab.research.factors.diagnostics import DiagnosticConfig, diagnose_factor
from ashare_lab.research.factors.models import FactorDiagnosticReport
from ashare_lab.research.factors.multiple_testing import PValueObservation, benjamini_hochberg
from ashare_lab.research.factors.selection import (
    FactorResearchReport,
    FactorSelectionError,
    select_factor_candidates,
)

_DEFAULT_DIAGNOSTIC_CONFIG: Final = DiagnosticConfig()


class FactorDiagnosticFrameSource(Protocol):
    """Load one development-only frame from verified immutable artifacts."""

    def load(self, trial: FactorTrial) -> pl.DataFrame:
        """Return the frame for exactly one registered trial."""
        ...


class AuditedFactorResearchService:
    """Verify immutable registration before calculating or selecting any factor."""

    def __init__(self, ledger: TrialLedgerStore) -> None:
        """Bind the service to the append-only source of declared attempts."""
        self._ledger = ledger

    def run(
        self,
        descriptor: TrialBatchDescriptor,
        inputs: tuple[FactorDiagnosticInput, ...],
        config: DiagnosticConfig = _DEFAULT_DIAGNOSTIC_CONFIG,
        maximum_q: float = 0.10,
    ) -> FactorResearchReport:
        """Produce a complete report only after exact batch registration is verified."""
        batch = self._ledger.read(descriptor)
        trial_ids = tuple(item.trial_id for item in batch.trials)
        input_ids = tuple(item.trial_id for item in inputs)
        if input_ids != trial_ids or len(set(input_ids)) != len(input_ids):
            detail = "diagnostic inputs must match the registered trial batch in exact order"
            raise FactorSelectionError(detail)
        reports = tuple(
            diagnose_factor(item.frame, trial, config)
            for item, trial in zip(inputs, batch.trials, strict=True)
        )
        return _build_report(
            batch,
            reports,
            same_family_correlations(inputs, batch.trials),
            maximum_q,
        )

    def run_streaming(
        self,
        descriptor: TrialBatchDescriptor,
        source: FactorDiagnosticFrameSource,
        config: DiagnosticConfig = _DEFAULT_DIAGNOSTIC_CONFIG,
        maximum_q: float = 0.10,
    ) -> FactorResearchReport:
        """Bound memory by diagnosing and correlating one registered family at a time."""
        batch = self._ledger.read(descriptor)
        reports: dict[str, FactorDiagnosticReport] = {}
        correlations: list[FactorCorrelation] = []
        families = tuple(dict.fromkeys(trial.family for trial in batch.trials))
        for family in families:
            trials = tuple(trial for trial in batch.trials if trial.family is family)
            inputs = tuple(
                FactorDiagnosticInput(trial.trial_id, source.load(trial)) for trial in trials
            )
            reports.update(
                (trial.trial_id, diagnose_factor(item.frame, trial, config))
                for item, trial in zip(inputs, trials, strict=True)
            )
            correlations.extend(same_family_correlations(inputs, trials))
        ordered = tuple(reports[trial.trial_id] for trial in batch.trials)
        return _build_report(batch, ordered, tuple(correlations), maximum_q)


def _build_report(
    batch: TrialBatch,
    reports: tuple[FactorDiagnosticReport, ...],
    correlations: tuple[FactorCorrelation, ...],
    maximum_q: float,
) -> FactorResearchReport:
    fdr = benjamini_hochberg(
        tuple(PValueObservation(trial_id=item.trial_id, p_value=item.p_value) for item in reports),
        maximum_q,
    )
    decisions = select_factor_candidates(
        batch.trials,
        reports,
        fdr,
        correlations,
    )
    return FactorResearchReport(
        batch_id=batch.batch_id,
        dataset_snapshot_id=batch.dataset_snapshot_id,
        maximum_q=maximum_q,
        diagnostics=reports,
        decisions=decisions,
    )
