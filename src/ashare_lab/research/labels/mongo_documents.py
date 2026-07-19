"""Pydantic trust-boundary documents for benchmark label evidence."""

from datetime import date

from pydantic import BaseModel, ConfigDict

from ashare_lab.research.features.market.mongo_documents import SnapshotDocument, parse_date


class BenchmarkQueryParams(BaseModel):
    """Closed index-daily request parameters used to qualify a snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ts_code: str
    start_date: str
    end_date: str


def benchmark_snapshot_range(
    snapshot: SnapshotDocument,
) -> tuple[str, date, date]:
    """Parse one benchmark snapshot into its symbol and closed date range."""
    params = BenchmarkQueryParams.model_validate_json(snapshot.request_params_canonical)
    return params.ts_code, parse_date(params.start_date), parse_date(params.end_date)
