"""Point-in-time selection and raw-value projection for financial factors."""

from datetime import datetime
from math import isfinite

from ashare_lab.research.features.financial.catalog import financial_factor_catalog
from ashare_lab.research.features.financial.models import (
    FinancialFactorInputError,
    FinancialFactorValue,
    FinancialIndicatorObservation,
    FinancialVersionConflictError,
)


def calculate_financial_factors(
    observations: tuple[FinancialIndicatorObservation, ...],
    symbol: str,
    decision_time: datetime,
    universe_available_at: datetime | None = None,
) -> tuple[FinancialFactorValue, ...]:
    """Select the latest visible report version and emit all six factors."""
    _validate_clocks(observations, symbol, decision_time)
    visible = tuple(item for item in observations if item.available_at <= decision_time)
    selected = _select_version(_fold_versions(visible))
    definitions = financial_factor_catalog()
    fallback = decision_time if universe_available_at is None else universe_available_at
    if fallback > decision_time:
        detail = "universe available_at exceeds decision_time"
        raise FinancialFactorInputError(detail)
    if selected is None:
        return tuple(
            _missing_value(symbol, decision_time, fallback, item.name, item.version)
            for item in definitions
        )
    values = (
        selected.roe,
        selected.grossprofit_margin,
        selected.ocf_to_debt,
        selected.debt_to_assets,
        selected.q_sales_yoy,
        selected.q_netprofit_yoy,
    )
    _validate_values(values)
    return tuple(
        FinancialFactorValue(
            symbol=symbol,
            decision_time=decision_time,
            feature_id=definition.name,
            feature_version=definition.version,
            value=value,
            available_at=max(fallback, selected.available_at),
            quality_status="ACCEPTED" if value is not None else "INCOMPLETE",
            null_reason=None if value is not None else "SOURCE_VALUE_MISSING",
            source_event_id=selected.event_id,
            source_report_period=selected.report_period,
            source_available_at=selected.available_at,
            source_update_flag=selected.update_flag,
            source_snapshot_id=selected.source_snapshot_id,
            source_row_sha256=selected.source_row_sha256,
        )
        for definition, value in zip(definitions, values, strict=True)
    )


def _validate_clocks(
    observations: tuple[FinancialIndicatorObservation, ...],
    symbol: str,
    decision_time: datetime,
) -> None:
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        detail = "decision_time must be timezone-aware"
        raise FinancialFactorInputError(detail)
    for item in observations:
        if item.symbol != symbol:
            detail = "financial series mixes symbols"
            raise FinancialFactorInputError(detail)
        if item.available_at.tzinfo is None or item.available_at.utcoffset() is None:
            detail = "source available_at must be timezone-aware"
            raise FinancialFactorInputError(detail)


def _validate_values(values: tuple[float | None, ...]) -> None:
    if any(value is not None and not isfinite(value) for value in values):
        detail = "selected financial metrics must be finite"
        raise FinancialFactorInputError(detail)


def _fold_versions(
    observations: tuple[FinancialIndicatorObservation, ...],
) -> tuple[FinancialIndicatorObservation, ...]:
    folded: dict[tuple[str, str, datetime, str | None], FinancialIndicatorObservation] = {}
    materials: dict[tuple[str, str, datetime, str | None], tuple[float | None, ...]] = {}
    for item in observations:
        key = (item.symbol, item.report_period, item.available_at, item.update_flag)
        material = (
            item.roe,
            item.grossprofit_margin,
            item.ocf_to_debt,
            item.debt_to_assets,
            item.q_sales_yoy,
            item.q_netprofit_yoy,
        )
        previous = materials.get(key)
        if previous is not None and previous != material:
            raise FinancialVersionConflictError(item.symbol, item.report_period, item.available_at)
        current = folded.get(key)
        if current is None or item.event_id < current.event_id:
            folded[key] = item
            materials[key] = material
    return tuple(folded.values())


def _select_version(
    observations: tuple[FinancialIndicatorObservation, ...],
) -> FinancialIndicatorObservation | None:
    if not observations:
        return None
    return max(
        observations,
        key=lambda item: (
            item.report_period,
            item.available_at,
            1 if item.update_flag == "1" else 0,
            item.event_id,
        ),
    )


def _missing_value(
    symbol: str,
    decision_time: datetime,
    available_at: datetime,
    feature_id: str,
    feature_version: str,
) -> FinancialFactorValue:
    return FinancialFactorValue(
        symbol=symbol,
        decision_time=decision_time,
        feature_id=feature_id,
        feature_version=feature_version,
        value=None,
        available_at=available_at,
        quality_status="INCOMPLETE",
        null_reason="NO_PUBLISHED_FINANCIAL",
        source_event_id=None,
        source_report_period=None,
        source_available_at=None,
        source_update_flag=None,
        source_snapshot_id=None,
        source_row_sha256=None,
    )
