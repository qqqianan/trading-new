from ashare_lab.research.factors.models import (
    ExpectedDirection,
    FactorDiagnosticReport,
    SegmentMetric,
)


def _diagnostic(autocorrelation: float) -> FactorDiagnosticReport:
    segment = SegmentMetric(segment="2024", observations=100, mean_rank_ic=0.01)
    return FactorDiagnosticReport(
        trial_id="factor_trial_" + "a" * 64,
        dataset_snapshot_id="ds_abc123",
        feature_name="factor_a",
        expected_direction=ExpectedDirection.HIGHER_IS_BETTER,
        total_sample_count=100,
        valid_pair_count=100,
        missing_feature_count=0,
        missing_label_count=0,
        coverage=1.0,
        raw_mean_rank_ic=0.01,
        oriented_mean_rank_ic=0.01,
        icir=0.1,
        direction_consistency=0.6,
        p_value=0.01,
        quintile_mean_labels=(0.0, 0.01, 0.02, 0.03, 0.04),
        quintile_monotonicity=1.0,
        top_bottom_gross_return=0.04,
        average_turnover=0.1,
        top_bottom_net_return=0.039,
        factor_autocorrelation=autocorrelation,
        size_exposure=0.01,
        yearly_segments=(segment,),
        regime_segments=(segment,),
        industry_segments=(),
        worst_year=segment,
        worst_industry=None,
    )


def test_factor_diagnostic_quantizes_submachine_float_noise() -> None:
    # Given: equivalent parallel reductions differing only in the last binary digit.
    first = 0.6850423029048068
    second = 0.685042302904807

    # When: both values cross the factor report trust boundary.
    reports = (_diagnostic(first), _diagnostic(second))

    # Then: insignificant reduction order cannot create a second artifact identity.
    assert reports[0] == reports[1]
