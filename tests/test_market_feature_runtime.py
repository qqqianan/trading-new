from datetime import date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.code_identity import GitEvidence
from ashare_lab.research.artifacts import ParquetArtifactStore, ResearchSchemaCatalog
from ashare_lab.research.universe import UniversePanelRow
from ashare_lab.research.universe.materialization import (
    UniverseMaterializationRequest,
    materialize_universe_panel,
)
from ashare_lab.services import market_feature_runtime
from ashare_lab.services.market_feature_contracts import (
    MarketFeatureMaterializationResult,
    MarketFeatureRunRequest,
    MarketFeatureServiceError,
)

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class Collection:
    pass


class Database:
    name = "ashare_quant"

    def __getitem__(self, _name: str) -> Collection:
        return Collection()


class Mongo:
    def __class_getitem__(cls, _item: type) -> type["Mongo"]:
        return cls

    def __init__(self, _uri: str, *, serverSelectionTimeoutMS: int) -> None:  # noqa: N803
        assert serverSelectionTimeoutMS == 8_000

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def __getitem__(self, name: str) -> Database:
        assert name == "ashare_quant"
        return Database()


def test_market_feature_runtime_binds_clean_commit_and_universe_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one real immutable universe artifact and a clean governed commit.
    artifact_root = tmp_path / "data" / "artifacts"
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    market_schema = market_feature_runtime.SchemaRegistry.load(
        ROOT / "schemas" / "tushare_p0_v1.json"
    )
    store = ParquetArtifactStore(artifact_root, catalog)
    decision = datetime(2026, 7, 10, 18, tzinfo=SHANGHAI)
    universe = materialize_universe_panel(
        store,
        catalog,
        (
            UniversePanelRow(
                symbol="000001.SZ",
                decision_time=decision,
                available_at=decision - timedelta(hours=1),
                eligible_for_new_risk=True,
                must_continue_marking=True,
                reason_codes=(),
            ),
        ),
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )
    captured: list[MarketFeatureRunRequest] = []

    def materialize(
        _reader: market_feature_runtime.MongoMarketFeatureReader,
        _store: ParquetArtifactStore,
        _schemas: ResearchSchemaCatalog,
        request: MarketFeatureRunRequest,
    ) -> MarketFeatureMaterializationResult:
        captured.append(request)
        return MarketFeatureMaterializationResult((), 0, 0, 0, 0)

    def clean_identity(_root: Path) -> GitEvidence:
        return GitEvidence("b" * 40, is_clean=True)

    def load_catalog(_paths: tuple[Path, ...]) -> ResearchSchemaCatalog:
        return catalog

    def load_market_schema(_path: Path) -> market_feature_runtime.SchemaRegistry:
        return market_schema

    monkeypatch.setattr(
        market_feature_runtime,
        "load_git_evidence",
        clean_identity,
    )
    monkeypatch.setattr(market_feature_runtime, "MongoClient", Mongo)
    monkeypatch.setattr(market_feature_runtime, "_UNIVERSE_ARTIFACT_ID", universe.artifact_id)
    monkeypatch.setattr(market_feature_runtime, "materialize_weekly_market_features", materialize)
    monkeypatch.setattr(
        market_feature_runtime.ResearchSchemaCatalog,
        "load",
        load_catalog,
    )
    monkeypatch.setattr(
        market_feature_runtime.SchemaRegistry,
        "load",
        load_market_schema,
    )

    # When: the local composition root constructs the governed run.
    result = market_feature_runtime.materialize_default_market_features(
        tmp_path,
        decision.date(),
        decision.date(),
    )

    # Then: code, universe, and input lineage come from immutable evidence.
    assert result.row_count == 0
    assert captured[0].materialization.code_commit == "b" * 40
    assert captured[0].materialization.universe_lineage_edge_id == universe.lineage_edge_id


def test_market_feature_runtime_rejects_dirty_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: code differs from the commit that would be written to lineage.
    def dirty_identity(_root: Path) -> GitEvidence:
        return GitEvidence("a" * 40, is_clean=False)

    monkeypatch.setattr(
        market_feature_runtime,
        "load_git_evidence",
        dirty_identity,
    )

    # When / Then: publication stops before schemas, Mongo, or artifacts are opened.
    with pytest.raises(MarketFeatureServiceError, match="dirty_worktree"):
        market_feature_runtime.materialize_default_market_features(
            ROOT,
            date(2026, 7, 10),
            date(2026, 7, 10),
        )
