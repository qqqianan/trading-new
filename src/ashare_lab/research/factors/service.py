"""Sole audited orchestration path from registered trials to factor decisions."""

from typing import Final

from ashare_lab.research.experiments.trial_ledger import (
    TrialBatchDescriptor,
    TrialLedgerStore,
)
from ashare_lab.research.factors.contracts import FactorDiagnosticInput
from ashare_lab.research.factors.correlation import same_family_correlations
from ashare_lab.research.factors.diagnostics import DiagnosticConfig, diagnose_factor
from ashare_lab.research.factors.multiple_testing import PValueObservation, benjamini_hochberg
from ashare_lab.research.factors.selection import (
    FactorResearchReport,
    FactorSelectionError,
    select_factor_candidates,
)

_DEFAULT_DIAGNOSTIC_CONFIG: Final = DiagnosticConfig()


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
        fdr = benjamini_hochberg(
            tuple(
                PValueObservation(trial_id=item.trial_id, p_value=item.p_value) for item in reports
            ),
            maximum_q,
        )
        decisions = select_factor_candidates(
            batch.trials,
            reports,
            fdr,
            same_family_correlations(inputs, batch.trials),
        )
        return FactorResearchReport(
            batch_id=batch.batch_id,
            dataset_snapshot_id=batch.dataset_snapshot_id,
            maximum_q=maximum_q,
            diagnostics=reports,
            decisions=decisions,
        )
