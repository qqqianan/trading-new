from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.features.financial import calculate_financial_factors
from ashare_lab.research.features.financial.materialization import (
    FinancialFeatureMaterializationRequest,
    materialize_financial_factor_artifacts,
)
from tests.test_financial_factors import financial_observation

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_financial_features_materialize_with_selected_version_provenance(
    tmp_path: Path,
) -> None:
    # Given: six PIT factor rows tied to one exact publication version.
    available = datetime(2025, 4, 30, 10, tzinfo=SHANGHAI)
    rows = calculate_financial_factors(
        (financial_observation("original", "20250331", available, 8.0),),
        "000001.SZ",
        available,
    )
    catalog = ResearchSchemaCatalog.load(
        (ROOT / "schemas" / "research_financial_feature_row_v1.json",)
    )
    store = ParquetArtifactStore(tmp_path, catalog)

    # When: the closed financial family is published.
    artifacts = materialize_financial_factor_artifacts(
        store,
        catalog,
        rows,
        FinancialFeatureMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            universe_artifact_id="universe_artifact_001",
            universe_lineage_edge_id="lineage_universe_001",
            code_commit="a" * 40,
        ),
    )

    # Then: every factor is isolated and retains its exact event and Raw row identity.
    assert len(artifacts) == 6
    frame = store.read(artifacts[0])
    assert frame["source_event_id"][0] == "event_original"
    assert frame["source_snapshot_id"][0] == "snapshot_original"
    assert frame["source_row_sha256"][0] == "a" * 64
