from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeCandidate,
    BridgeStatus,
    CninfoIndustryBridgeAudit,
)
from ashare_lab.data.official_bridge_candidates import (
    CandidateReaderError,
    MongoOfficialBridgeCandidateReader,
)
from ashare_lab.services.cninfo_bridge_batch import build_cninfo_bridge_batch
from ashare_lab.services.cninfo_bridge_batch_artifacts import (
    write_cninfo_bridge_batch,
    write_cninfo_bridge_selection,
)
from ashare_lab.services.cninfo_bridge_sampling import select_stratified_candidates


class Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.documents = documents
        self.queries: list[BsonDocument] = []

    def find(
        self,
        query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        self.queries.append(query)
        assert projection is not None
        return self.documents


class Database:
    name = "ashare_quant"

    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.collection = Collection(documents)

    def __getitem__(self, name: str) -> Collection:
        assert name == "pit_security_events"
        return self.collection


def test_candidate_reader_prefers_listed_and_uses_first_traded_only_as_fallback() -> None:
    # Given: one stock has both lifecycle facts and another only conservative evidence.
    database = Database(
        (
            _event("listed-1", "301001.SZ", "LISTED", date(2022, 1, 3)),
            _event("listed-1-replay", "301001.SZ", "LISTED", date(2022, 1, 3)),
            _event("first-1", "301001.SZ", "FIRST_TRADED", date(2022, 1, 4)),
            _event("first-2", "688001.SH", "FIRST_TRADED", date(2022, 2, 7)),
        )
    )

    # When: the exact-schema candidate interval is read.
    candidates = MongoOfficialBridgeCandidateReader(database).read(
        date(2021, 11, 10),
        date(2024, 2, 8),
        "schema_universe",
    )

    # Then: each symbol has one stable upstream fact without mixing fallback dates.
    assert tuple((item.symbol, item.event_type) for item in candidates) == (
        ("301001.SZ", "LISTED"),
        ("688001.SH", "FIRST_TRADED"),
    )
    assert candidates[0].listing_date == date(2022, 1, 3)
    assert candidates[0].source_event_ids == ("listed-1", "listed-1-replay")
    assert database.collection.queries[0]["schema_manifest_id"] == "schema_universe"


def test_candidate_reader_rejects_conflicting_preferred_lifecycle_facts() -> None:
    # Given: one symbol has two accepted LISTED facts with different effective dates.
    database = Database(
        (
            _event("listed-1", "301001.SZ", "LISTED", date(2022, 1, 3)),
            _event("listed-2", "301001.SZ", "LISTED", date(2022, 1, 4)),
        )
    )

    # When / Then: ambiguous source lineage fails closed.
    with pytest.raises(CandidateReaderError, match="conflicting lifecycle facts"):
        MongoOfficialBridgeCandidateReader(database).read(
            date(2021, 11, 10),
            date(2024, 2, 8),
            "schema_universe",
        )


def test_candidate_reader_can_replay_exact_local_evidence_cutoff() -> None:
    # Given: accepted lifecycle evidence later replayed after the frozen pilot selection.
    database = Database((_event("listed-1", "301001.SZ", "LISTED", date(2022, 1, 3)),))
    cutoff = datetime(2026, 7, 24, 9, 5, tzinfo=UTC)

    # When: the source universe is reconstructed at the original local evidence cutoff.
    MongoOfficialBridgeCandidateReader(database).read(
        date(2021, 11, 10),
        date(2024, 2, 8),
        "schema_universe",
        ingested_before=cutoff,
    )

    # Then: later replay event IDs cannot mutate the frozen candidate lineage.
    assert database.collection.queries[0]["ingested_at"] == {"$lt": cutoff}


def test_stratified_selection_is_stable_and_covers_every_nonempty_stratum(
    tmp_path: Path,
) -> None:
    # Given: nine year-exchange strata with unequal candidate counts.
    database = Database(
        tuple(
            _event(
                f"event-{year}-{exchange}-{index}",
                f"{year % 100:02d}{index:04d}.{exchange}",
                "LISTED",
                date(year, 1, min(index + 1, 28)),
            )
            for year in (2021, 2022, 2023)
            for exchange in ("SZ", "SH", "BJ")
            for index in range(1, 6 + year - 2021)
        )
    )
    candidates = MongoOfficialBridgeCandidateReader(database).read(
        date(2021, 1, 1), date(2024, 1, 1), "schema_universe"
    )

    # When: the fixed v1 protocol selects the same batch twice.
    first = select_stratified_candidates(candidates, sample_size=30)
    second = select_stratified_candidates(tuple(reversed(candidates)), sample_size=30)
    artifact = write_cninfo_bridge_selection(first, tmp_path)

    # Then: selection is order-independent, exact-sized, and represents all strata.
    assert first == second
    assert len(first.selected) == 30
    assert len(first.strata) == 9
    assert all(stratum.quota >= 1 for stratum in first.strata)
    assert sum(stratum.quota for stratum in first.strata) == 30
    assert artifact.path.parent.name == first.selection_id


def test_batch_report_keeps_selected_failure_without_replacement(tmp_path: Path) -> None:
    # Given: two fixed selected candidates and one failed individual source audit.
    database = Database(
        (
            _event("listed-1", "301001.SZ", "LISTED", date(2022, 1, 3)),
            _event("listed-2", "688001.SH", "LISTED", date(2022, 2, 7)),
        )
    )
    candidates = MongoOfficialBridgeCandidateReader(database).read(
        date(2022, 1, 1), date(2023, 1, 1), "schema_universe"
    )
    selection = select_stratified_candidates(candidates, sample_size=2)
    audits = tuple(_missing_audit(item.symbol, item.listing_date) for item in selection.selected)

    # When: the immutable batch report is assembled from exact candidate keys.
    report = build_cninfo_bridge_batch(
        selection,
        audits,
        audited_at=datetime(2026, 7, 24, 2, tzinfo=UTC),
    )
    first = write_cninfo_bridge_batch(report, tmp_path)
    second = write_cninfo_bridge_batch(report, tmp_path)

    # Then: failures remain in place and the report cannot authorize research use.
    assert report.missing_count == 2
    assert tuple(item.candidate.symbol for item in report.audits) == (
        "688001.SH",
        "301001.SZ",
    )
    assert report.research_use_authorized is False
    assert first == second
    assert first.path.parent.name == report.batch_id


def _event(
    event_id: str,
    symbol: str,
    event_type: str,
    effective_date: date,
) -> BsonDocument:
    observed = datetime(2026, 7, 24, 1, tzinfo=UTC)
    effective_at = datetime(
        effective_date.year,
        effective_date.month,
        effective_date.day,
        tzinfo=UTC,
    )
    return {
        "event_id": event_id,
        "ts_code": symbol,
        "event_type": event_type,
        "effective_at": effective_at,
        "available_at": observed,
        "schema_manifest_id": "schema_universe",
        "quality_status": "ACCEPTED",
    }


def _missing_audit(symbol: str, listing_date: date) -> CninfoIndustryBridgeAudit:
    return CninfoIndustryBridgeAudit(
        audit_id=f"cninfo_industry_bridge_audit_{symbol[:6] * 10}0000",
        audit_version="cninfo_industry_bridge_audit_v1",
        audited_at=datetime(2026, 7, 24, 2, tzinfo=UTC),
        candidate=BridgeCandidate(symbol=symbol, listing_date=listing_date),
        status=BridgeStatus.MISSING,
        failure_reason="final_listing_announcement_missing",
        evidence=None,
        research_use_authorized=False,
    )
