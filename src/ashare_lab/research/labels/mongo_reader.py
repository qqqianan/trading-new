"""Read-only composition for stock and benchmark label evidence."""

from datetime import date

from ashare_lab.research.features.market.mongo_contracts import MarketDatabase
from ashare_lab.research.labels.models import (
    BenchmarkOpenObservation,
    LabelReaderError,
    LabelTradeObservation,
)
from ashare_lab.research.labels.mongo_benchmark_reader import read_benchmark_observations
from ashare_lab.research.labels.mongo_stock_reader import read_stock_observations
from ashare_lab.research.universe.mongo_reader import MongoUniversePanelReader


class MongoLabelEvidenceReader:
    """Load only accepted exact-schema evidence needed by the future target."""

    def __init__(self, database: MarketDatabase) -> None:
        """Bind without owning or mutating the Mongo connection."""
        if database.name != "ashare_quant":
            detail = f"requires ashare_quant, got {database.name}"
            raise LabelReaderError(detail)
        self._database = database
        self._calendar = MongoUniversePanelReader(database)

    def open_dates(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[date, ...]:
        """Load accepted SSE sessions from the exact market schema."""
        return self._calendar.open_dates(start_date, end_date, schema_manifest_id)

    def stock_observations(
        self,
        start_date: date,
        end_date: date,
        schema_manifest_id: str,
    ) -> tuple[LabelTradeObservation, ...]:
        """Load raw stock opens with fixed-session execution constraints."""
        return read_stock_observations(
            self._database,
            start_date,
            end_date,
            schema_manifest_id,
        )

    def benchmark_observations(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        schema_manifest_id: str,
    ) -> tuple[BenchmarkOpenObservation, ...]:
        """Load one exact benchmark's accepted raw opens and provenance."""
        return read_benchmark_observations(
            self._database,
            start_date,
            end_date,
            symbol,
            schema_manifest_id,
        )
