from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pymongo import UpdateOne

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import CanonicalBatch
from ashare_lab.data.cashflow_documents import cashflow_document, cashflow_lineage
from ashare_lab.data.cashflow_store import MongoCashflowStore
from ashare_lab.data.cashflows import build_cashflow_version
from ashare_lab.data.queries import cashflow_security_queries
from ashare_lab.data.schema_registry import SchemaContractError
from tests.cashflow_support import canonical_batch, canonical_record, registry

SHANGHAI = ZoneInfo("Asia/Shanghai")


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

    def update_one(self, _query: BsonDocument, _update: BsonDocument, *, upsert: bool) -> None:
        assert upsert is True
        self.update_calls += 1


class Database:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}

    def __getitem__(self, name: str) -> Collection:
        return self.collections.setdefault(name, Collection())


def _store(database: Database) -> MongoCashflowStore:
    store = MongoCashflowStore.__new__(MongoCashflowStore)
    store.__dict__["_database"] = database
    return store


def test_cashflow_version_and_documents_use_actual_publication_clock() -> None:
    # Given: one schema-valid cash-flow row observed after publication.
    record = canonical_record()

    # When: it crosses PIT and closed-document boundaries.
    event = build_cashflow_version(record)
    document = cashflow_document(event)
    lineage = cashflow_lineage(event)

    # Then: actual publication controls visibility and all source fields have lineage.
    assert event.available_at == datetime(2026, 3, 22, 18, 0, tzinfo=SHANGHAI)
    assert event.n_cashflow_act == 12.0
    assert document["free_cashflow"] == 26.0
    mappings = lineage["field_mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) == len(registry().endpoint("cashflow").fields) + 1
    assert record.quality_status == "QUARANTINED"


def test_cashflow_store_persists_events_and_empty_batch_evidence() -> None:
    # Given: one accepted version and an isolated Mongo fake.
    event = build_cashflow_version(canonical_record())
    database = Database()
    store = _store(database)

    # When: populated and empty canonical batches are persisted.
    result = store.write_batch(canonical_batch(), (event,))
    empty = CanonicalBatch(
        "canonical_cashflow_empty",
        "snap",
        "schema",
        "raw_to_canonical",
        "1.1.2",
        "QUARANTINED",
        "canonical_cashflow_statement",
        (),
        (),
    )
    empty_result = store.write_batch(empty, ())

    # Then: events and both kinds of governance evidence are present.
    assert result.inserted_count == 1
    assert empty_result.event_count == 0
    assert database["pit_cashflow_statements"].bulk_calls == 1
    assert database["meta_quality_reports"].update_calls == 2
    assert database["meta_lineage_edges"].update_calls == 2


def test_cashflow_queries_pin_code_range_and_schema_projection() -> None:
    # Given: two historical lifecycle codes.
    schema_registry = registry()

    # When: standard-interface requests are built.
    queries = cashflow_security_queries(
        schema_registry, ("000001.SZ", "600000.SH"), "20200101", "20260716"
    )

    # Then: code, range, endpoint, and fields are all explicit.
    assert tuple(query.endpoint for query in queries) == ("cashflow", "cashflow")
    assert tuple(query.params[0].value for query in queries) == ("000001.SZ", "600000.SH")
    assert queries[0].fields == schema_registry.endpoint("cashflow").field_names


@pytest.mark.parametrize(("field", "value"), [("ann_date", 1), ("net_profit", "bad")])
def test_cashflow_version_rejects_malformed_optional_values(
    field: str,
    value: str | int,
) -> None:
    # Given: one provider value that violates the committed field type.
    record = canonical_record()
    payload = dict(record.business_fields)
    payload[field] = value
    invalid = replace(record, business_fields=tuple(payload.items()))

    # When / Then: malformed dynamic values cannot cross the PIT boundary.
    with pytest.raises(SchemaContractError, match="cash-flow source field is invalid"):
        build_cashflow_version(invalid)
