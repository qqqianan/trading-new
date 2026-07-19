from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.research.artifacts import ArtifactKind, ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.labels.calculator import (
    calculate_relative_open_return,
    resolve_label_window,
)
from ashare_lab.research.labels.materialization import (
    LabelMaterializationRequest,
    materialize_label_rows,
)
from ashare_lab.research.labels.models import LabelWindowEvidence
from tests.test_labels import benchmark_observation, label_sessions, stock_observation

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_label_materialization_preserves_four_raw_price_lineages(tmp_path: Path) -> None:
    # Given: one complete future window with stock and benchmark Raw identities.
    sessions = label_sessions(date(2025, 1, 3), 22)
    decision = datetime(2025, 1, 3, 18, tzinfo=SHANGHAI)
    window = resolve_label_window(sessions, decision)
    row = calculate_relative_open_return(
        "000001.SZ",
        decision,
        window,
        LabelWindowEvidence(
            stock_observation(window.entry_date, 100.0),
            stock_observation(window.exit_date, 110.0),
            benchmark_observation(window.entry_date, 1_000.0),
            benchmark_observation(window.exit_date, 1_050.0),
        ),
    )
    catalog = ResearchSchemaCatalog.load((ROOT / "schemas" / "research_label_row_v1.json",))
    store = ParquetArtifactStore(tmp_path, catalog)

    # When: the target is published through the physically isolated label writer.
    artifact = materialize_label_rows(
        store,
        catalog,
        (row,),
        LabelMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            universe_artifact_id="universe_artifact_001",
            universe_lineage_edge_id="lineage_universe_001",
            code_commit="a" * 40,
        ),
    )

    # Then: exact sources survive and the artifact cannot alias a feature directory.
    frame = store.read(artifact)
    assert artifact.kind is ArtifactKind.LABEL
    assert artifact.parquet_path.parent.parent.name == "label"
    assert frame["entry_price_source_row_sha256"][0] == "b" * 64
    assert frame["exit_constraint_source_row_sha256"][0] == "c" * 64
    assert frame["benchmark_exit_source_row_sha256"][0] == "d" * 64
