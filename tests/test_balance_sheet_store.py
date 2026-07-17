from pymongo import UpdateOne

from ashare_lab.data.balance_sheet_documents import (
    balance_sheet_document,
    balance_sheet_lineage,
)
from ashare_lab.data.balance_sheet_store import MongoBalanceSheetStore
from ashare_lab.data.balance_sheets import build_balance_sheet_version
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import CanonicalBatch
from tests.balance_sheet_support import canonical_batch, canonical_record, registry


class BulkResult:
    upserted_count = 1


class Collection:
    def __init__(self) -> None:
        self.bulk_calls = 0
        self.update_calls = 0

    def bulk_write(self, operations: list[UpdateOne], *, ordered: bool) -> BulkResult:
        assert operations
        assert ordered is False
        self.bulk_calls += 1
        return BulkResult()

    def update_one(
        self,
        _query: BsonDocument,
        _update: BsonDocument,
        *,
        upsert: bool,
    ) -> None:
        assert upsert is True
        self.update_calls += 1


class Database:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}

    def __getitem__(self, name: str) -> Collection:
        return self.collections.setdefault(name, Collection())


def _store(database: Database) -> MongoBalanceSheetStore:
    store = MongoBalanceSheetStore.__new__(MongoBalanceSheetStore)
    store.__dict__["_database"] = database
    return store


def test_balance_sheet_documents_and_store_cover_closed_fields() -> None:
    # Given: one schema-valid publication-timed balance sheet.
    event = build_balance_sheet_version(canonical_record())
    database = Database()

    # When: documents and the event batch cross the Mongo boundary.
    document = balance_sheet_document(event)
    lineage = balance_sheet_lineage(event)
    result = _store(database).write_batch(canonical_batch(), (event,))

    # Then: fields, quality, lineage, and the accepted event are all persisted.
    assert document["total_liab_hldr_eqy"] == 180.0
    mappings = lineage["field_mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) == len(registry().endpoint("balancesheet").fields) + 1
    assert result.inserted_count == 1
    assert database["pit_balance_sheets"].bulk_calls == 1
    assert database["meta_quality_reports"].bulk_calls == 1
    assert database["meta_lineage_edges"].bulk_calls == 1


def test_empty_balance_sheet_response_writes_batch_evidence() -> None:
    # Given: a quarantined canonical artifact with no provider rows.
    batch = CanonicalBatch(
        artifact_id="canonical_balance_empty",
        source_snapshot_id="snap_balance_empty",
        schema_manifest_id="schema_balance",
        transform_name="tushare_raw_to_canonical",
        transform_version="1.1.2",
        quality_status="QUARANTINED",
        collection="canonical_balance_sheet",
        records=(),
        field_mappings=(),
    )
    database = Database()

    # When: PIT projection completes.
    result = _store(database).write_batch(batch, ())

    # Then: no event is invented and both completion proofs are written.
    assert result.event_count == 0
    assert database["meta_quality_reports"].update_calls == 1
    assert database["meta_lineage_edges"].update_calls == 1
