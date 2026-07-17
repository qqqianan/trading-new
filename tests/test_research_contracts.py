from datetime import date

import pytest

from ashare_lab.domain.market import Symbol
from ashare_lab.governance import DataQualityGuard, ModelTrainingGuard
from ashare_lab.ml.registry import (
    ModelPromotionError,
    ModelRecord,
    ModelStatus,
    promote_model,
)
from ashare_lab.portfolio import PortfolioTarget, TargetPosition
from ashare_lab.research.features import FeatureDefinition, FeatureValueType
from ashare_lab.research.labels import LabelDefinition, LabelPrice
from ashare_lab.research.model_governance import TrainingApproval
from ashare_lab.research.splits import WalkForwardConfig, build_walk_forward_folds
from ashare_lab.research.splits.walk_forward import SplitIntegrityError


def test_feature_label_and_portfolio_contracts_preserve_research_boundaries() -> None:
    # Given: versioned point-in-time feature and execution-aligned label definitions.
    feature = FeatureDefinition(
        name="momentum_20d",
        version="v1",
        description="Twenty-day raw-price momentum available after close.",
        value_type=FeatureValueType.FLOAT,
        lookback_trading_days=20,
        source_fields=("close",),
    )
    label = LabelDefinition(
        name="excess_open_to_open_20d",
        version="v1",
        holding_period_trading_days=20,
        benchmark_symbol="000300.SH",
    )

    # When: a model score is converted into portfolio intent.
    target = PortfolioTarget(
        decision_date=date(2026, 7, 14),
        model_id="lgbm_ranker_001",
        positions=(TargetPosition(Symbol("600519.SH"), weight=0.05, score=1.42),),
        cash_weight=0.95,
    )

    # Then: feature, label, and target remain distinct immutable contracts.
    assert feature.requires_available_at is True
    assert label.entry_lag_trading_days == 1
    assert label.entry_price is LabelPrice.OPEN
    assert target.positions[0].weight == 0.05


def test_governance_package_is_the_stable_public_facade() -> None:
    # Given / When: callers import governance through its public package.
    quality_guard = DataQualityGuard()
    training_guard = ModelTrainingGuard()

    # Then: both non-bypassable gates are available without internal imports.
    assert quality_guard.__class__.__name__ == "DataQualityGuard"
    assert training_guard.__class__.__name__ == "ModelTrainingGuard"


def test_walk_forward_rejects_non_increasing_dates() -> None:
    # Given: a split protocol and duplicated observation date.
    duplicated = (date(2020, 1, 1), date(2020, 1, 1))
    config = WalkForwardConfig(1, 1, 1, 1, 0, 0)

    # When / Then: time-order corruption is rejected before fold construction.
    with pytest.raises(SplitIntegrityError, match="strictly increasing"):
        build_walk_forward_folds(duplicated, config)


def test_model_registry_rejects_promotion_without_approval() -> None:
    # Given: a draft model whose training protocol was rejected.
    draft = ModelRecord("model_001", "ds_abc", "run_001", ModelStatus.DRAFT)
    rejection = TrainingApproval(
        approved=False,
        rulebook_version="1.1.0",
        checks=(),
    )

    # When / Then: registry state cannot bypass governance.
    with pytest.raises(ModelPromotionError, match="requires an approved"):
        promote_model(draft, rejection)
