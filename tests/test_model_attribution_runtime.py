from pathlib import Path

import pytest

from ashare_lab.research.model_attribution.store import (
    ModelAttributionDescriptor,
    ModelAttributionStore,
)
from ashare_lab.services.model_attribution_runtime import (
    ModelAttributionRuntimeError,
    run_model_performance_attribution,
)

from .test_model_diagnostic_runtime import publish_model_diagnostic_fixture


def publish_model_attribution_fixture(
    tmp_path: Path,
) -> tuple[ModelAttributionDescriptor, str, str, str, str]:
    """Publish one real diagnostic-to-attribution chain for adjacent tests."""
    diagnostic, model_id, baseline_id, model_backtest_id = publish_model_diagnostic_fixture(
        tmp_path
    )
    descriptor = run_model_performance_attribution(tmp_path, diagnostic.report_id)
    return descriptor, diagnostic.report_id, model_id, baseline_id, model_backtest_id


def test_attribution_runtime_reads_exact_parent_chain_and_publishes_report(
    tmp_path: Path,
) -> None:
    # Given: one real diagnosis backed by model, keyed predictions, targets, and backtests.
    # When: attribution resolves every child only from the exact parent diagnosis.
    descriptor, diagnostic_id, model_id, baseline_id, model_backtest_id = (
        publish_model_attribution_fixture(tmp_path)
    )

    # Then: the report binds the complete chain and remains development-only evidence.
    report = ModelAttributionStore(tmp_path / "data" / "artifacts").read(descriptor)
    assert report.diagnostic_report_id == diagnostic_id
    assert report.model_id == model_id
    assert report.baseline_backtest_id == baseline_id
    assert report.model_backtest_id == model_backtest_id
    assert report.tuning_permitted is False
    assert report.final_test_runs == 0


def test_attribution_runtime_translates_missing_parent_to_stable_blocker(
    tmp_path: Path,
) -> None:
    # Given: an artifact root without the requested immutable parent diagnosis.
    (tmp_path / "data" / "artifacts").mkdir(parents=True)

    # When / Then: storage details are translated at the composition boundary.
    with pytest.raises(ModelAttributionRuntimeError, match="model_attribution_runtime"):
        run_model_performance_attribution(
            tmp_path,
            "model_diagnostic_" + "a" * 64,
        )
