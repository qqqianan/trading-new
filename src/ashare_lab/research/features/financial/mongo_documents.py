"""Pydantic trust boundary for accepted financial PIT documents."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from ashare_lab.research.features.financial.models import FinancialIndicatorObservation

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class FinancialIndicatorDocument(BaseModel):
    """Exact fields required from one accepted PIT indicator version."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str
    ts_code: str
    available_at: datetime
    end_date: str
    update_flag: str | None = None
    roe: float | None = None
    grossprofit_margin: float | None = None
    ocf_to_debt: float | None = None
    debt_to_assets: float | None = None
    q_sales_yoy: float | None = None
    q_netprofit_yoy: float | None = None
    source_snapshot_id: str
    source_row_sha256: str
    schema_manifest_id: str
    quality_status: str


def financial_observation(document: FinancialIndicatorDocument) -> FinancialIndicatorObservation:
    """Restore the announcement clock and preserve exact source identity."""
    value = document.available_at
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return FinancialIndicatorObservation(
        event_id=document.event_id,
        symbol=document.ts_code,
        available_at=utc_value.astimezone(_SHANGHAI),
        report_period=document.end_date,
        update_flag=document.update_flag,
        roe=document.roe,
        grossprofit_margin=document.grossprofit_margin,
        ocf_to_debt=document.ocf_to_debt,
        debt_to_assets=document.debt_to_assets,
        q_sales_yoy=document.q_sales_yoy,
        q_netprofit_yoy=document.q_netprofit_yoy,
        source_snapshot_id=document.source_snapshot_id,
        source_row_sha256=document.source_row_sha256,
    )
