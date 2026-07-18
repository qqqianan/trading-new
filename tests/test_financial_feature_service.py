from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_lab.research.artifacts import (
    ArtifactDescriptor,
    ParquetArtifactStore,
    ResearchSchemaCatalog,
)
from ashare_lab.research.features.financial.materialization import (
    FinancialFeatureMaterializationRequest,
)
from ashare_lab.research.features.financial.models import FinancialIndicatorObservation
from ashare_lab.research.universe import UniversePanelRow
from ashare_lab.research.universe.materialization import (
    UniverseMaterializationRequest,
    materialize_universe_panel,
)
from ashare_lab.services.financial_feature_contracts import FinancialFeatureRunRequest
from ashare_lab.services.financial_feature_materialization import (
    FinancialFeatureServiceError,
    materialize_weekly_financial_features,
)

ROOT = Path(__file__).parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class FinancialEvidenceReader:
    def __init__(self, observations: tuple[FinancialIndicatorObservation, ...]) -> None:
        self._observations = observations
        self.read_count = 0

    def read(
        self,
        end_time: datetime,
        schema_manifest_id: str,
    ) -> tuple[FinancialIndicatorObservation, ...]:
        assert schema_manifest_id == "schema_financial"
        self.read_count += 1
        return tuple(item for item in self._observations if item.available_at <= end_time)


def test_financial_feature_service_preserves_missing_keys_and_revision_timing(
    tmp_path: Path,
) -> None:
    # Given: one symbol has an original and later revision while another has no publication.
    first_decision = datetime(2025, 5, 2, 18, tzinfo=SHANGHAI)
    second_decision = datetime(2025, 5, 16, 18, tzinfo=SHANGHAI)
    original = _observation("original", datetime(2025, 4, 30, 10, tzinfo=SHANGHAI), 8.0)
    revision = _observation("revision", datetime(2025, 5, 10, 10, tzinfo=SHANGHAI), 9.0)
    catalog, store, universe = _universe(
        tmp_path,
        (
            _universe_row("000001.SZ", first_decision),
            _universe_row("000002.SZ", first_decision),
            _universe_row("000001.SZ", second_decision),
            _universe_row("000002.SZ", second_decision),
        ),
    )

    # When: the governed service publishes the complete weekly panel.
    result = materialize_weekly_financial_features(
        FinancialEvidenceReader((revision, original)),
        store,
        catalog,
        _request(universe, first_decision.date(), second_decision.date()),
    )

    # Then: all keys survive and the selected event changes only after publication.
    assert result.row_count == 24
    assert result.universe_key_count == 4
    roe = store.read(result.artifacts[0]).sort(["decision_time", "symbol"])
    assert roe["value"].to_list() == [8.0, None, 9.0, None]
    assert roe["source_event_id"].to_list() == [
        "event_original",
        None,
        "event_revision",
        None,
    ]
    assert roe["null_reason"].to_list() == [
        None,
        "NO_PUBLISHED_FINANCIAL",
        None,
        "NO_PUBLISHED_FINANCIAL",
    ]
    assert roe["source_row_sha256"].to_list() == ["a" * 64, None, "b" * 64, None]


def test_financial_feature_service_rejects_universe_identity_alias(tmp_path: Path) -> None:
    # Given: the run claims an artifact other than the immutable universe being read.
    decision = datetime(2025, 5, 2, 18, tzinfo=SHANGHAI)
    catalog, store, universe = _universe(
        tmp_path,
        (_universe_row("000001.SZ", decision),),
    )
    request = _request(universe, decision.date(), decision.date())
    aliased = replace(
        request,
        materialization=request.materialization.model_copy(
            update={"universe_artifact_id": "universe_artifact_wrong"}
        ),
    )

    # When / Then: identity mismatch closes the gate before the PIT reader runs.
    reader = FinancialEvidenceReader(())
    with pytest.raises(FinancialFeatureServiceError, match="universe_identity_mismatch"):
        materialize_weekly_financial_features(reader, store, catalog, aliased)
    assert reader.read_count == 0


def test_financial_feature_service_rejects_universe_lineage_alias(tmp_path: Path) -> None:
    # Given: the artifact ID is genuine but its lineage edge is replaced.
    decision = datetime(2025, 5, 2, 18, tzinfo=SHANGHAI)
    catalog, store, universe = _universe(
        tmp_path,
        (_universe_row("000001.SZ", decision),),
    )
    request = _request(universe, decision.date(), decision.date())
    aliased = replace(
        request,
        materialization=request.materialization.model_copy(
            update={"universe_lineage_edge_id": "lineage_wrong"}
        ),
    )

    # When / Then: an aliased edge fails before accepted PIT evidence is read.
    reader = FinancialEvidenceReader(())
    with pytest.raises(FinancialFeatureServiceError, match="universe_identity_mismatch"):
        materialize_weekly_financial_features(reader, store, catalog, aliased)
    assert reader.read_count == 0


def test_financial_feature_service_rejects_late_universe_evidence(tmp_path: Path) -> None:
    # Given: the universe key itself was not available at its declared decision clock.
    decision = datetime(2025, 5, 2, 18, tzinfo=SHANGHAI)
    late = replace(
        _universe_row("000001.SZ", decision),
        available_at=decision + timedelta(seconds=1),
    )
    catalog, store, universe = _universe(tmp_path, (late,))

    # When / Then: PIT-invalid universe evidence is rejected before financial access.
    reader = FinancialEvidenceReader(())
    with pytest.raises(FinancialFeatureServiceError, match="invalid_universe_evidence"):
        materialize_weekly_financial_features(
            reader,
            store,
            catalog,
            _request(universe, decision.date(), decision.date()),
        )
    assert reader.read_count == 0


def _universe(
    root: Path,
    rows: tuple[UniversePanelRow, ...],
) -> tuple[ResearchSchemaCatalog, ParquetArtifactStore, ArtifactDescriptor]:
    catalog = ResearchSchemaCatalog.load(
        (
            ROOT / "schemas" / "research_financial_feature_row_v1.json",
            ROOT / "schemas" / "research_universe_row_v1.json",
        )
    )
    store = ParquetArtifactStore(root, catalog)
    artifact = materialize_universe_panel(
        store,
        catalog,
        rows,
        UniverseMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            code_commit="a" * 40,
        ),
    )
    return catalog, store, artifact


def _request(
    universe: ArtifactDescriptor,
    start: date,
    end: date,
) -> FinancialFeatureRunRequest:
    return FinancialFeatureRunRequest(
        start_date=start,
        end_date=end,
        financial_schema_manifest_id="schema_financial",
        universe_artifact=universe,
        materialization=FinancialFeatureMaterializationRequest(
            input_manifest_id="inputs_001",
            input_lineage_manifest_id="lineage_inputs_001",
            universe_artifact_id=universe.artifact_id,
            universe_lineage_edge_id=universe.lineage_edge_id,
            code_commit="a" * 40,
        ),
    )


def _universe_row(symbol: str, decision: datetime) -> UniversePanelRow:
    return UniversePanelRow(
        symbol=symbol,
        decision_time=decision,
        available_at=decision - timedelta(hours=1),
        eligible_for_new_risk=True,
        must_continue_marking=True,
        reason_codes=(),
    )


def _observation(name: str, available_at: datetime, roe: float) -> FinancialIndicatorObservation:
    return FinancialIndicatorObservation(
        event_id=f"event_{name}",
        symbol="000001.SZ",
        available_at=available_at,
        report_period="20250331",
        update_flag="1" if name == "revision" else "0",
        roe=roe,
        grossprofit_margin=30.0,
        ocf_to_debt=0.2,
        debt_to_assets=50.0,
        q_sales_yoy=12.0,
        q_netprofit_yoy=15.0,
        source_snapshot_id=f"snapshot_{name}",
        source_row_sha256=("b" if name == "revision" else "a") * 64,
    )
