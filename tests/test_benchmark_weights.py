from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.data.benchmark_weights import (
    build_index_weight_event,
    validate_index_weight_batch,
)
from ashare_lab.data.canonical import CanonicalBatch, canonicalize_batch
from ashare_lab.data.schema_registry import SchemaContractError, SchemaRegistry
from ashare_lab.data.snapshots import SnapshotTiming, build_raw_snapshot
from ashare_lab.data.tushare_client import TushareClient, TushareQuery

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _batch(
    weights: tuple[float, ...], trade_dates: tuple[str, ...] | None = None
) -> CanonicalBatch:
    registry = SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")
    schema = registry.endpoint("index_weight")
    dates = trade_dates or ("20260331",) * len(weights)
    values = tuple(
        ("000300.SH", f"{number:06d}.SZ", dates[number], weight)
        for number, weight in enumerate(weights)
    )
    observed = datetime(2026, 7, 17, 18, 30, tzinfo=SHANGHAI)
    raw = build_raw_snapshot(
        TushareQuery("index_weight", (), schema.field_names),
        TushareClient.table_for_test(schema.field_names, values),
        schema,
        registry.manifest_id,
        SnapshotTiming(observed, observed),
    )
    return canonicalize_batch(raw, schema, registry.manifest_id)


def test_index_weight_event_uses_weight_date_close_clock() -> None:
    # Given: a complete two-constituent monthly weight publication.
    batch = _batch((60.0, 40.0))

    # When: it crosses the PIT validation and event boundary.
    validate_index_weight_batch(batch)
    event = build_index_weight_event(batch.records[0])

    # Then: canonical remains isolated and close publication controls visibility.
    assert batch.quality_status == "QUARANTINED"
    assert event.available_at == datetime(2026, 3, 31, 16, 0, tzinfo=SHANGHAI)
    assert event.weight == 60.0


def test_index_weight_batch_rejects_multiple_publication_dates() -> None:
    # Given: one monthly response mixing two historical weight dates.
    batch = _batch((60.0, 40.0), ("20260330", "20260331"))

    # When / Then: an ambiguous month cannot become accepted PIT evidence.
    with pytest.raises(SchemaContractError, match="one publication date"):
        validate_index_weight_batch(batch)


def test_index_weight_batch_rejects_incomplete_weight_sum() -> None:
    # Given: a monthly response whose weights cannot describe a complete index.
    incomplete = _batch((10.0, 20.0))

    # When / Then: the incomplete batch cannot cross the PIT boundary.
    with pytest.raises(SchemaContractError, match="sum is incomplete"):
        validate_index_weight_batch(incomplete)


def test_index_weight_event_rejects_nonpositive_weight() -> None:
    # Given: a provider row with a nonpositive constituent weight.
    invalid = _batch((0.0, 100.0))

    # When / Then: the malformed value cannot cross the event boundary.
    with pytest.raises(SchemaContractError, match="weight"):
        build_index_weight_event(invalid.records[0])
