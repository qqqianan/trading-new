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
from ashare_lab.services import financial_feature_runtime
from ashare_lab.services.financial_feature_contracts import (
    FinancialFeatureMaterializationResult,
    FinancialFeatureRunRequest,
    FinancialFeatureServiceError,
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


def test_financial_feature_runtime_binds_clean_commit_and_universe_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one immutable universe artifact and a clean governed commit.
    artifact_root = tmp_path / "data" / "artifacts"
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_financial_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
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
    captured: list[FinancialFeatureRunRequest] = []

    def materialize(
        _reader: financial_feature_runtime.MongoFinancialFactorReader,
        _store: ParquetArtifactStore,
        _schemas: ResearchSchemaCatalog,
        request: FinancialFeatureRunRequest,
    ) -> FinancialFeatureMaterializationResult:
        captured.append(request)
        return FinancialFeatureMaterializationResult((), 0, 0, 0, 0)

    def clean_identity(_root: Path) -> GitEvidence:
        return GitEvidence("b" * 40, is_clean=True)

    def load_catalog(_paths: tuple[Path, ...]) -> ResearchSchemaCatalog:
        return catalog

    financial_schema = financial_feature_runtime.SchemaRegistry.load(
        ROOT / "schemas" / "tushare_financial_indicator_v1.json"
    )

    def load_financial_schema(_path: Path) -> financial_feature_runtime.SchemaRegistry:
        return financial_schema

    monkeypatch.setattr(
        financial_feature_runtime,
        "load_git_evidence",
        clean_identity,
    )
    monkeypatch.setattr(financial_feature_runtime, "MongoClient", Mongo)
    monkeypatch.setattr(financial_feature_runtime, "_UNIVERSE_ARTIFACT_ID", universe.artifact_id)
    monkeypatch.setattr(
        financial_feature_runtime,
        "materialize_weekly_financial_features",
        materialize,
    )
    monkeypatch.setattr(
        financial_feature_runtime.ResearchSchemaCatalog,
        "load",
        load_catalog,
    )
    monkeypatch.setattr(
        financial_feature_runtime.SchemaRegistry,
        "load",
        load_financial_schema,
    )

    # When: the local composition root constructs the financial factor run.
    result = financial_feature_runtime.materialize_default_financial_features(
        tmp_path,
        decision.date(),
        decision.date(),
    )

    # Then: code, current PIT schema, and immutable input lineage are bound exactly.
    assert result.row_count == 0
    assert captured[0].materialization.code_commit == "b" * 40
    assert captured[0].materialization.universe_lineage_edge_id == universe.lineage_edge_id
    assert captured[0].financial_schema_manifest_id.startswith("schema_")


def test_financial_feature_runtime_rejects_dirty_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: local code differs from the commit proposed for lineage.
    def dirty_identity(_root: Path) -> GitEvidence:
        return GitEvidence("a" * 40, is_clean=False)

    monkeypatch.setattr(
        financial_feature_runtime,
        "load_git_evidence",
        dirty_identity,
    )

    # When / Then: publication stops before schemas, Mongo, or artifacts are opened.
    with pytest.raises(FinancialFeatureServiceError, match="dirty_worktree"):
        financial_feature_runtime.materialize_default_financial_features(
            ROOT,
            date(2026, 7, 10),
            date(2026, 7, 10),
        )
