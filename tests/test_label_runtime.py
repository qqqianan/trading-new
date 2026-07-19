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
from ashare_lab.services import label_runtime
from ashare_lab.services.label_contracts import (
    LabelMaterializationResult,
    LabelRunRequest,
    LabelServiceError,
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


def test_label_runtime_binds_clean_commit_schemas_and_universe_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one immutable universe artifact and a clean governed commit.
    artifact_root = tmp_path / "data" / "artifacts"
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_label_row_v1.json",
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
    captured: list[LabelRunRequest] = []

    def materialize(
        _reader: label_runtime.MongoLabelEvidenceReader,
        _store: ParquetArtifactStore,
        _schemas: ResearchSchemaCatalog,
        request: LabelRunRequest,
    ) -> LabelMaterializationResult:
        captured.append(request)
        return LabelMaterializationResult(universe, 0, 0, 0)

    def clean_identity(_root: Path) -> GitEvidence:
        return GitEvidence("b" * 40, is_clean=True)

    def load_catalog(_paths: tuple[Path, ...]) -> ResearchSchemaCatalog:
        return catalog

    market = label_runtime.SchemaRegistry.load(ROOT / "schemas" / "tushare_p0_v1.json")
    benchmark = label_runtime.SchemaRegistry.load(ROOT / "schemas" / "tushare_benchmarks_v1.json")

    def load_schema(path: Path) -> label_runtime.SchemaRegistry:
        return benchmark if "benchmarks" in path.name else market

    monkeypatch.setattr(label_runtime, "load_git_evidence", clean_identity)
    monkeypatch.setattr(label_runtime, "MongoClient", Mongo)
    monkeypatch.setattr(label_runtime, "_UNIVERSE_ARTIFACT_ID", universe.artifact_id)
    monkeypatch.setattr(label_runtime, "materialize_weekly_labels", materialize)
    monkeypatch.setattr(label_runtime.ResearchSchemaCatalog, "load", load_catalog)
    monkeypatch.setattr(label_runtime.SchemaRegistry, "load", load_schema)

    # When: the local composition root constructs the cutoff-bounded label run.
    label_runtime.materialize_default_labels(
        tmp_path,
        decision.date(),
        decision.date(),
        date(2026, 7, 16),
    )

    # Then: code, exact source schemas, universe, and evidence cutoff are immutable inputs.
    assert captured[0].materialization.code_commit == "b" * 40
    assert captured[0].market_schema_manifest_id == market.manifest_id
    assert captured[0].benchmark_schema_manifest_id == benchmark.manifest_id
    assert captured[0].evidence_end_date == date(2026, 7, 16)


def test_label_runtime_rejects_dirty_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: local source differs from the code identity proposed for lineage.
    def dirty_identity(_root: Path) -> GitEvidence:
        return GitEvidence("a" * 40, is_clean=False)

    monkeypatch.setattr(label_runtime, "load_git_evidence", dirty_identity)

    # When / Then: publication stops before schema, artifact, or Mongo access.
    with pytest.raises(LabelServiceError, match="dirty_worktree"):
        label_runtime.materialize_default_labels(
            ROOT,
            date(2026, 7, 10),
            date(2026, 7, 10),
            date(2026, 7, 16),
        )
