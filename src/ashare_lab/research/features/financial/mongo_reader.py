"""Read-only current-schema adapter for financial PIT factor evidence."""

from datetime import datetime
from typing import TYPE_CHECKING

from ashare_lab.research.features.financial.models import FinancialIndicatorObservation
from ashare_lab.research.features.financial.mongo_contracts import (
    FinancialDatabase,
    FinancialReaderError,
)
from ashare_lab.research.features.financial.mongo_documents import (
    FinancialIndicatorDocument,
    financial_observation,
)

if TYPE_CHECKING:
    from ashare_lab.data.bson_types import BsonDocument


class MongoFinancialFactorReader:
    """Load accepted PIT indicator versions without canonical access."""

    def __init__(self, database: FinancialDatabase) -> None:
        """Bind only to the isolated governed database."""
        if database.name != "ashare_quant":
            detail = f"requires ashare_quant, got {database.name}"
            raise FinancialReaderError(detail)
        self._database = database

    def read(
        self,
        end_time: datetime,
        schema_manifest_id: str,
    ) -> tuple[FinancialIndicatorObservation, ...]:
        """Read versions visible by one timezone-aware upper cutoff."""
        if end_time.tzinfo is None or end_time.utcoffset() is None:
            detail = "end_time must be timezone-aware"
            raise FinancialReaderError(detail)
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "quality_status": "ACCEPTED",
            "available_at": {"$lte": end_time},
        }
        projection: BsonDocument = {"_id": 0}
        projection.update(dict.fromkeys(FinancialIndicatorDocument.model_fields, 1))
        parsed = tuple(
            FinancialIndicatorDocument.model_validate(document)
            for document in self._database["pit_financial_indicators"].find(query, projection)
        )
        qualified = tuple(
            financial_observation(item)
            for item in parsed
            if item.schema_manifest_id == schema_manifest_id and item.quality_status == "ACCEPTED"
        )
        return tuple(item for item in qualified if item.available_at <= end_time)
