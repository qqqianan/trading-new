from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.features.market import calculate_market_factors
from ashare_lab.research.features.market.materialization import (
    MarketFeatureMaterializationRequest,
    materialize_market_factor_artifacts,
)
from tests.test_market_factors import market_observations

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_market_features_materialize_as_fifteen_isolated_content_artifacts(
    tmp_path: Path,
) -> None:
    # Given: one complete governed factor row set and closed upstream manifests.
    observations = market_observations(121)
    decision = datetime.combine(observations[-1].bar.trading_date, time(18), SHANGHAI)
    rows = calculate_market_factors(observations, decision)
    catalog = ResearchSchemaCatalog.load((ROOT / "schemas" / "research_feature_row_v1.json",))
    store = ParquetArtifactStore(tmp_path, catalog)
    request = MarketFeatureMaterializationRequest(
        input_manifest_id="inputs_001",
        input_lineage_manifest_id="lineage_manifest_001",
        universe_artifact_id="universe_artifact_001",
        universe_lineage_edge_id="lineage_universe_001",
        code_commit="a" * 40,
    )

    # When: identical factor content is published twice.
    first = materialize_market_factor_artifacts(store, catalog, rows, request)
    second = materialize_market_factor_artifacts(store, catalog, rows, request)

    # Then: every registered factor owns one stable exact-schema artifact.
    assert first == second
    assert len(first) == 15
    assert len({item.artifact_id for item in first}) == 15
    assert all(item.row_count == 1 for item in first)
    assert len(tuple((tmp_path / "feature").iterdir())) == 15
