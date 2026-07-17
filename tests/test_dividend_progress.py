from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.corporate_action_progress import completed_dividend_dates
from ashare_lab.data.corporate_action_store import dividend_batch_artifact_id


class EvidenceCollection:
    """Return fixed documents through Mongo-shaped find operations."""

    def __init__(self, documents: list[BsonDocument]) -> None:
        self.documents = documents

    def find(self, _query: BsonDocument) -> list[BsonDocument]:
        return self.documents

    def find_one(
        self,
        query: BsonDocument,
        _projection: BsonDocument | None = None,
    ) -> BsonDocument | None:
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ),
            None,
        )


class EvidenceDatabase:
    """Expose one complete or incomplete dividend evidence chain."""

    def __init__(self, *, include_quality: bool) -> None:
        schema = "schema_dividend"
        canonical = "canonical_dividend"
        batch = dividend_batch_artifact_id(canonical)
        quality: list[BsonDocument] = (
            [{"artifact_id": batch, "passed": True}] if include_quality else []
        )
        self.collections = {
            "meta_source_snapshots": EvidenceCollection(
                [
                    {
                        "snapshot_id": "snap_dividend",
                        "request_params_canonical": '{"ann_date":"20260710"}',
                    }
                ]
            ),
            "meta_lineage_edges": EvidenceCollection(
                [
                    {
                        "upstream_artifact_id": "snap_dividend",
                        "downstream_artifact_id": canonical,
                        "output_schema_id": schema,
                        "transform_name": "tushare_raw_to_canonical",
                    },
                    {
                        "upstream_artifact_id": canonical,
                        "downstream_artifact_id": batch,
                        "output_schema_id": schema,
                    },
                ]
            ),
            "meta_quality_reports": EvidenceCollection(quality),
        }

    def __getitem__(self, name: str) -> EvidenceCollection:
        return self.collections[name]


def test_completed_dividend_date_requires_full_pit_evidence_chain() -> None:
    # Given: accepted Raw, canonical lineage, PIT lineage, and passed PIT quality.
    database = EvidenceDatabase(include_quality=True)

    # When: resume state is derived from persisted evidence.
    completed = completed_dividend_dates(database, "schema_dividend", "20260701", "20260731")

    # Then: the exact announcement date is safe to skip.
    assert completed == frozenset({"20260710"})


def test_dividend_date_without_passed_pit_quality_remains_pending() -> None:
    # Given: a date whose evidence chain lacks passed PIT batch quality.
    database = EvidenceDatabase(include_quality=False)

    # When: resume state is derived.
    completed = completed_dividend_dates(database, "schema_dividend", "20260701", "20260731")

    # Then: the date cannot be skipped.
    assert completed == frozenset()
