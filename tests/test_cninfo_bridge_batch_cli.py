from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from ashare_lab import cninfo_bridge_batch_cli
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.cninfo_industry_bridge import (
    BridgeCandidate,
    BridgeStatus,
    CninfoIndustryBridgeAudit,
)
from ashare_lab.data.cninfo_prospectus_bridge import (
    CninfoProspectusBridgeAudit,
    ProspectusBridgeCandidate,
)
from ashare_lab.data.official_bridge_candidates import OfficialBridgeCandidate
from ashare_lab.services.cninfo_bridge_batch import build_cninfo_bridge_batch
from ashare_lab.services.cninfo_bridge_batch_artifacts import write_cninfo_bridge_batch
from ashare_lab.services.cninfo_bridge_sampling import select_stratified_candidates


class Collection:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.documents = documents

    def find(
        self,
        _query: BsonDocument,
        projection: BsonDocument | None = None,
    ) -> tuple[BsonDocument, ...]:
        assert projection is not None
        return self.documents


class Database:
    name = "ashare_quant"

    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.collection = Collection(documents)

    def __getitem__(self, name: str) -> Collection:
        assert name == "pit_security_events"
        return self.collection


class Mongo:
    def __init__(self, documents: tuple[BsonDocument, ...]) -> None:
        self.database = Database(documents)

    def __class_getitem__(cls, _item: type) -> type["Mongo"]:
        return cls

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
        return self.database


class Http:
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


def test_pilot_runtime_persists_selection_before_complete_failure_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the exact 842-stock governed population and source audits that all fail closed.
    documents = tuple(_event(index) for index in range(1, 843))

    class Client(Mongo):
        def __init__(self, _uri: str, *, serverSelectionTimeoutMS: int) -> None:  # noqa: N803
            assert serverSelectionTimeoutMS == 8_000
            super().__init__(documents)

    def provider_factory(_http: Http, _pacer: cninfo_bridge_batch_cli.RequestPacer) -> str:
        return "provider"

    def audit_candidate(
        _provider: str,
        candidate: BridgeCandidate,
        *,
        audited_at: datetime,
    ) -> CninfoIndustryBridgeAudit:
        return CninfoIndustryBridgeAudit(
            audit_id=f"cninfo_industry_bridge_audit_{candidate.symbol[:6] * 10}0000",
            audit_version="cninfo_industry_bridge_audit_v4",
            audited_at=audited_at,
            candidate=candidate,
            status=BridgeStatus.MISSING,
            failure_reason="explicit_industry_disclosure_missing",
            evidence=None,
            research_use_authorized=False,
        )

    monkeypatch.setattr(cninfo_bridge_batch_cli, "MongoClient", Client)
    monkeypatch.setattr(cninfo_bridge_batch_cli, "create_provider_client", Http)
    monkeypatch.setattr(cninfo_bridge_batch_cli, "CninfoArchiveClient", provider_factory)
    monkeypatch.setattr(cninfo_bridge_batch_cli, "audit_cninfo_candidate", audit_candidate)

    # When: the operator runtime executes the fixed pilot protocol.
    cninfo_bridge_batch_cli.run_pilot(project_root=Path.cwd(), output_root=tmp_path)

    # Then: the frozen selection, all 30 failures, and one batch remain durable.
    assert len(tuple(tmp_path.glob("cninfo_bridge_selections/*/manifest.json"))) == 1
    assert len(tuple(tmp_path.glob("cninfo_industry_bridge/*/manifest.json"))) == 30
    assert len(tuple(tmp_path.glob("cninfo_bridge_batches/*/manifest.json"))) == 1


def test_prospectus_runtime_uses_only_parent_missing_audits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an immutable parent batch with seven misses and one excluded conflict.
    upstream = tuple(
        OfficialBridgeCandidate(
            symbol=f"{index:06d}.SZ",
            listing_date=datetime(2022, 7, index, tzinfo=UTC).date(),
            source_event_ids=(f"event-{index}",),
            universe_schema_manifest_id="schema_universe",
            event_type="LISTED",
            quality_status="ACCEPTED",
        )
        for index in range(1, 9)
    )
    selection = select_stratified_candidates(upstream, sample_size=8)
    base_audits = tuple(
        _base_audit(
            item.symbol,
            item.listing_date,
            "explicit_industry_disclosure_missing" if index < 7 else "conflicting",
        )
        for index, item in enumerate(selection.selected)
    )
    parent = build_cninfo_bridge_batch(
        selection,
        base_audits,
        audited_at=datetime(2026, 7, 27, tzinfo=UTC),
    )
    parent_artifact = write_cninfo_bridge_batch(parent, tmp_path / "parents")

    def provider_factory(_http: Http, _pacer: cninfo_bridge_batch_cli.RequestPacer) -> str:
        return "provider"

    def audit_candidate(
        _provider: str,
        candidate: ProspectusBridgeCandidate,
        *,
        audited_at: datetime,
    ) -> CninfoProspectusBridgeAudit:
        return CninfoProspectusBridgeAudit(
            audit_id=f"cninfo_prospectus_bridge_audit_{candidate.symbol[:6] * 10}0000",
            audit_version="cninfo_prospectus_bridge_audit_v1",
            audited_at=audited_at,
            candidate=candidate,
            status=BridgeStatus.MISSING,
            failure_reason="final_prospectus_missing",
            evidence=None,
            research_use_authorized=False,
        )

    monkeypatch.setattr(cninfo_bridge_batch_cli, "_PARENT_BATCH_ID", parent.batch_id)
    monkeypatch.setattr(cninfo_bridge_batch_cli, "create_provider_client", Http)
    monkeypatch.setattr(cninfo_bridge_batch_cli, "CninfoArchiveClient", provider_factory)
    monkeypatch.setattr(
        cninfo_bridge_batch_cli,
        "audit_cninfo_prospectus_candidate",
        audit_candidate,
    )

    # When: the supplemental operator runs from the exact parent manifest.
    cninfo_bridge_batch_cli.run_prospectus_pilot(
        parent_batch_path=parent_artifact.path,
        output_root=tmp_path,
    )

    # Then: seven parent misses persist; the conflict is never queried or replaced.
    assert len(tuple(tmp_path.glob("cninfo_prospectus_bridge/*/manifest.json"))) == 7
    assert len(tuple(tmp_path.glob("cninfo_prospectus_batches/*/manifest.json"))) == 1


def _event(index: int) -> BsonDocument:
    exchange = ("SZ", "SH", "BJ")[index % 3]
    effective_at = datetime(2022, (index % 12) + 1, (index % 27) + 1, tzinfo=UTC)
    return {
        "event_id": f"event-{index}",
        "ts_code": f"{index:06d}.{exchange}",
        "event_type": "LISTED",
        "effective_at": effective_at,
        "available_at": datetime(2026, 7, 24, tzinfo=UTC),
        "schema_manifest_id": (
            "schema_49b36e8944a757ca01f221a1f3137e8605dd49ec2ea5d561b7d258ac84a141da"
        ),
        "quality_status": "ACCEPTED",
    }


def _base_audit(symbol: str, listing_date: date, reason: str) -> CninfoIndustryBridgeAudit:
    return CninfoIndustryBridgeAudit(
        audit_id=f"cninfo_industry_bridge_audit_{symbol[:6] * 10}0000",
        audit_version="cninfo_industry_bridge_audit_v4",
        audited_at=datetime(2026, 7, 27, tzinfo=UTC),
        candidate=BridgeCandidate(symbol=symbol, listing_date=listing_date),
        status=BridgeStatus.MISSING,
        failure_reason=reason,
        evidence=None,
        research_use_authorized=False,
    )
