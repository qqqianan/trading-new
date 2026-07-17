from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.universe import UniverseAdmissionSpec, UniversePanelRow
from ashare_lab.research.universe.materialization import (
    UniverseMaterializationRequest,
    materialize_universe_panel,
)

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_universe_panel_materializes_with_input_manifest_lineage(tmp_path: Path) -> None:
    # Given: one PIT row and a qualified input/lineage manifest pair.
    catalog = ResearchSchemaCatalog.load((ROOT / "schemas" / "research_universe_row_v1.json",))
    store = ParquetArtifactStore(tmp_path, catalog)
    request = UniverseMaterializationRequest(
        input_manifest_id="inputs_001",
        input_lineage_manifest_id="lineage_manifest_001",
        code_commit="a" * 40,
    )
    row = UniversePanelRow(
        symbol="000001.SZ",
        decision_time=datetime(2026, 7, 17, 18, tzinfo=SHANGHAI),
        available_at=datetime(2026, 7, 17, 16, tzinfo=SHANGHAI),
        eligible_for_new_risk=True,
        must_continue_marking=True,
        reason_codes=(),
    )

    # When: the same governed panel is materialized twice.
    first = materialize_universe_panel(store, catalog, (row,), request)
    second = materialize_universe_panel(store, catalog, (row,), request)

    # Then: identity is stable and the exact registered universe schema is readable.
    assert first == second
    assert first.kind.value == "universe"
    assert store.read(first).schema == catalog.polars_schema(first.kind)


def test_universe_rule_change_changes_artifact_identity(tmp_path: Path) -> None:
    # Given: one panel and two materially different admission contracts.
    catalog = ResearchSchemaCatalog.load((ROOT / "schemas" / "research_universe_row_v1.json",))
    store = ParquetArtifactStore(tmp_path, catalog)
    request = UniverseMaterializationRequest(
        input_manifest_id="inputs_001",
        input_lineage_manifest_id="lineage_manifest_001",
        code_commit="a" * 40,
    )
    row = UniversePanelRow(
        symbol="000001.SZ",
        decision_time=datetime(2026, 7, 17, 18, tzinfo=SHANGHAI),
        available_at=datetime(2026, 7, 17, 16, tzinfo=SHANGHAI),
        eligible_for_new_risk=True,
        must_continue_marking=True,
        reason_codes=(),
    )

    # When: both contracts publish the same current row values.
    first = materialize_universe_panel(store, catalog, (row,), request)
    second = materialize_universe_panel(
        store,
        catalog,
        (row,),
        request,
        UniverseAdmissionSpec(min_median_amount_cny=30_000_000.0),
    )

    # Then: parameters remain part of artifact identity even before rows diverge.
    assert first.artifact_id != second.artifact_id
