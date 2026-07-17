from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.canonical import canonicalize_batch
from ashare_lab.data.mongo_documents import canonical_document
from ashare_lab.data.mongo_store import StoredSnapshot
from ashare_lab.data.schema_registry import SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.sync_service import SyncResult
from ashare_lab.data.tushare_client import TushareClient, TushareQuery
from ashare_lab.data.universe import SecurityEventType
from ashare_lab.data.universe_pipeline import (
    _first_trade_fallbacks,
    build_universe_events,
)

PROJECT_ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
OBSERVED = datetime(2026, 7, 16, 18, 30, tzinfo=SHANGHAI)


class DistinctCollection:
    """Return fixed code identities and reject unnecessary row scans."""

    def __init__(self, codes: list[str]) -> None:
        self.codes = codes

    def distinct(self, _field: str, _query: BsonDocument) -> list[str]:
        return self.codes

    def find_one(
        self,
        _query: BsonDocument,
        *,
        sort: list[tuple[str, int]],
    ) -> BsonDocument | None:
        assert sort
        msg = "persisted lifecycle evidence should prevent fallback row scans"
        raise AssertionError(msg)


class PersistedEventDatabase:
    """Expose matching persisted lifecycle and daily code sets."""

    def __init__(self) -> None:
        self.collections = {
            "pit_security_events": DistinctCollection(["000001.SZ"]),
            "canonical_daily_bar": DistinctCollection(["000001.SZ"]),
        }

    def __getitem__(self, name: str) -> DistinctCollection:
        return self.collections[name]


class FallbackDailyCollection(DistinctCollection):
    """Expose one accepted first daily record for a missing lifecycle code."""

    def __init__(self, document: BsonDocument) -> None:
        super().__init__(["300114.SZ"])
        self.document = document

    def find_one(
        self,
        _query: BsonDocument,
        *,
        sort: list[tuple[str, int]],
    ) -> BsonDocument:
        assert sort == [("trade_date", 1)]
        return self.document


class FallbackDatabase:
    """Expose no lifecycle evidence and one accepted daily source row."""

    def __init__(self, document: BsonDocument) -> None:
        self.collections = {
            "pit_security_events": DistinctCollection([]),
            "canonical_daily_bar": FallbackDailyCollection(document),
        }

    def __getitem__(self, name: str) -> DistinctCollection:
        return self.collections[name]


def test_empty_sync_reuses_persisted_lifecycle_before_building_fallbacks() -> None:
    # Given: no new batch events but an already-persisted listing for every daily code.
    daily = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    universe = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    database = PersistedEventDatabase()

    # When: conservative fallback coverage is recalculated.
    fallback = _first_trade_fallbacks(database, daily, universe, ())

    # Then: persisted lifecycle evidence prevents duplicate first-trade scans and events.
    assert fallback == ()


def test_governed_universe_batches_build_lifecycle_and_name_events() -> None:
    # Given: one master row and one historical name row under the universe schema.
    registry = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    master = _sync_result(
        registry,
        "stock_basic",
        (
            "000001.SZ",
            "000001",
            "平安银行",
            "深圳",
            "银行",
            "平安银行股份有限公司",
            None,
            "payh",
            "主板",
            "SZSE",
            "CNY",
            "L",
            "19910403",
            None,
            "S",
            None,
            None,
        ),
    )
    name = _sync_result(
        registry,
        "namechange",
        ("000001.SZ", "ST平安", "20200501", "20200630", "20200430", "ST"),
    )

    # When: the governed batches cross the PIT transformation boundary.
    events = build_universe_events(registry, (master, name))

    # Then: listing, current state, and historical ST state are all eventized.
    assert tuple(event.event_type for event in events) == (
        SecurityEventType.LISTED,
        SecurityEventType.NAME_STATUS,
        SecurityEventType.NAME_STATUS,
    )


def test_missing_lifecycle_uses_first_accepted_daily_bar_as_fallback() -> None:
    # Given: an accepted daily row whose code has no persisted lifecycle event.
    daily = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_p0_v1.json")
    universe = SchemaRegistry.load(PROJECT_ROOT / "schemas" / "tushare_universe_v1.json")
    result = _sync_result(
        daily,
        "daily",
        (
            "300114.SZ",
            "20200102",
            10.0,
            10.5,
            9.8,
            10.2,
            None,
            0.2,
            2.0,
            1000.0,
            10200.0,
        ),
    )
    record = canonicalize_batch(
        result.batch,
        daily.endpoint("daily"),
        daily.manifest_id,
    ).records[0]
    database = FallbackDatabase(canonical_document(record))

    # When: lifecycle coverage is completed from accepted daily evidence.
    fallback = _first_trade_fallbacks(database, daily, universe, ())

    # Then: the event is conservative and preserves its cross-schema source.
    assert fallback[0].event_type is SecurityEventType.FIRST_TRADED
    assert fallback[0].input_schema_manifest_id == daily.manifest_id
    assert fallback[0].schema_manifest_id == universe.manifest_id


def _sync_result(
    registry: SchemaRegistry,
    endpoint: str,
    values: tuple[str | float | None, ...],
) -> SyncResult:
    schema = registry.endpoint(endpoint)
    query = TushareQuery(endpoint=endpoint, params=(), fields=schema.field_names)
    batch = build_raw_snapshot(
        query,
        TushareClient.table_for_test(schema.field_names, (values,)),
        schema,
        registry.manifest_id,
        SnapshotTiming(OBSERVED, OBSERVED),
    )
    stored = StoredSnapshot(batch.snapshot.snapshot_id, len(batch.rows), inserted=True)
    return SyncResult(stored=stored, batch=batch)
