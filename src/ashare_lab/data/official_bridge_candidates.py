"""Read-only lifecycle evidence for official industry bridge audits."""

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ashare_lab.data.bson_types import BsonDocument

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class CandidateCollection(Protocol):
    """Minimal Mongo collection capability required by the source audit."""

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> Iterable[BsonDocument]:
        """Return lifecycle documents matching one governed query."""
        ...


class CandidateDatabase(Protocol):
    """Minimal database capability required by the read-only adapter."""

    @property
    def name(self) -> str:
        """Return the governed database name."""
        ...

    def __getitem__(self, name: str) -> CandidateCollection:
        """Return one named collection without granting write capability."""
        ...


class LifecycleCandidateDocument(BaseModel):
    """Validated accepted lifecycle fields used for candidate enumeration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    ts_code: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    event_type: Literal["LISTED", "FIRST_TRADED"]
    effective_at: datetime
    available_at: datetime
    schema_manifest_id: str
    quality_status: Literal["ACCEPTED"]


class OfficialBridgeCandidate(BaseModel):
    """One immutable candidate with exact upstream lifecycle lineage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    listing_date: date
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    universe_schema_manifest_id: str
    event_type: Literal["LISTED", "FIRST_TRADED"]
    quality_status: Literal["ACCEPTED"]

    @property
    def exchange(self) -> str:
        """Return the exchange suffix used by the fixed sampling strata."""
        return self.symbol.rsplit(".", maxsplit=1)[1]


class CandidateReaderError(Exception):
    """Candidate lifecycle facts cannot form one unambiguous source universe."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        """Record a stable source-only audit failure."""
        super().__init__()
        self.detail = detail

    def __str__(self) -> str:
        """Return the adapter boundary and failure detail."""
        return f"official_bridge_candidate_reader: {self.detail}"


class MongoOfficialBridgeCandidateReader:
    """Read exact-schema accepted listing evidence without modifying MongoDB."""

    def __init__(self, database: CandidateDatabase) -> None:
        """Bind only to the governed project database."""
        if database.name != "ashare_quant":
            detail = f"requires ashare_quant, got {database.name}"
            raise CandidateReaderError(detail)
        self._database = database

    def read(
        self,
        start_date: date,
        end_exclusive: date,
        schema_manifest_id: str,
        *,
        ingested_before: datetime | None = None,
    ) -> tuple[OfficialBridgeCandidate, ...]:
        """Read a half-open effective-date interval and fold fallback facts."""
        start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=_SHANGHAI)
        end = datetime(
            end_exclusive.year,
            end_exclusive.month,
            end_exclusive.day,
            tzinfo=_SHANGHAI,
        )
        query: BsonDocument = {
            "schema_manifest_id": schema_manifest_id,
            "quality_status": "ACCEPTED",
            "event_type": {"$in": ["LISTED", "FIRST_TRADED"]},
            "effective_at": {"$gte": start, "$lt": end},
        }
        if ingested_before is not None:
            query["ingested_at"] = {"$lt": ingested_before}
        projection: BsonDocument = {
            "_id": 0,
            "event_id": 1,
            "ts_code": 1,
            "event_type": 1,
            "effective_at": 1,
            "available_at": 1,
            "schema_manifest_id": 1,
            "quality_status": 1,
        }
        documents = tuple(
            LifecycleCandidateDocument.model_validate(document)
            for document in self._database["pit_security_events"].find(query, projection)
        )
        return _fold_candidates(documents, schema_manifest_id)


def candidate_universe_sha256(candidates: tuple[OfficialBridgeCandidate, ...]) -> str:
    """Hash the complete ordered source universe independently of selection."""
    payload = json.dumps(
        [item.model_dump(mode="json") for item in sorted(candidates, key=lambda item: item.symbol)],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _fold_candidates(
    documents: tuple[LifecycleCandidateDocument, ...],
    schema_manifest_id: str,
) -> tuple[OfficialBridgeCandidate, ...]:
    grouped: dict[str, list[LifecycleCandidateDocument]] = {}
    for document in documents:
        grouped.setdefault(document.ts_code, []).append(document)
    return tuple(
        _preferred_candidate(symbol, tuple(events), schema_manifest_id)
        for symbol, events in sorted(grouped.items())
    )


def _preferred_candidate(
    symbol: str,
    events: tuple[LifecycleCandidateDocument, ...],
    schema_manifest_id: str,
) -> OfficialBridgeCandidate:
    listed = tuple(event for event in events if event.event_type == "LISTED")
    preferred = listed or tuple(event for event in events if event.event_type == "FIRST_TRADED")
    listing_dates = {_shanghai_date(event.effective_at) for event in preferred}
    if len(listing_dates) != 1:
        detail = f"conflicting lifecycle facts for {symbol}"
        raise CandidateReaderError(detail)
    event = preferred[0]
    return OfficialBridgeCandidate(
        symbol=symbol,
        listing_date=_shanghai_date(event.effective_at),
        source_event_ids=tuple(sorted({item.event_id for item in preferred})),
        universe_schema_manifest_id=schema_manifest_id,
        event_type=event.event_type,
        quality_status=event.quality_status,
    )


def _shanghai_date(value: datetime) -> date:
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.astimezone(_SHANGHAI).date()
