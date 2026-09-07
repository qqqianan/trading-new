from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest
from typer.testing import CliRunner

from ashare_lab import cninfo_full_discovery_cli
from ashare_lab.data.bson_types import BsonDocument
from ashare_lab.data.cninfo_listing_discovery import (
    CninfoDiscoveryStatus,
    CninfoListingDiscoveryAudit,
)
from ashare_lab.data.official_bridge_candidates import (
    MongoOfficialBridgeCandidateReader,
    OfficialBridgeCandidate,
)
from ashare_lab.services.cninfo_full_discovery import (
    build_full_discovery_plan,
    freeze_full_candidate_selection,
)
from tests.test_cninfo_bridge_batch_cli import _event


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
    documents: tuple[BsonDocument, ...] = ()

    def __init__(self, _uri: str, *, serverSelectionTimeoutMS: int) -> None:  # noqa: N803
        assert serverSelectionTimeoutMS == 8_000
        self.database = Database(self.documents)

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


def test_full_plan_cli_persists_842_candidates_before_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the governed database reproduces exactly 842 accepted lifecycle candidates.
    Mongo.documents = tuple(_event(index) for index in range(1, 843))
    monkeypatch.setattr(cninfo_full_discovery_cli, "MongoClient", Mongo)
    candidates = MongoOfficialBridgeCandidateReader(Database(Mongo.documents)).read(
        datetime(2021, 11, 10, tzinfo=UTC).date(),
        datetime(2024, 2, 8, tzinfo=UTC).date(),
        "schema_49b36e8944a757ca01f221a1f3137e8605dd49ec2ea5d561b7d258ac84a141da",
    )
    expected_hash = freeze_full_candidate_selection(candidates).candidate_universe_sha256
    monkeypatch.setattr(
        cninfo_full_discovery_cli,
        "_expected_universe_sha256",
        lambda: expected_hash,
    )

    # When: the operator creates a full discovery plan.
    result = CliRunner().invoke(
        cninfo_full_discovery_cli.app,
        ["plan", "--project-root", str(Path.cwd()), "--output-root", str(tmp_path)],
    )

    # Then: one full selection and one 17-shard plan persist before network access.
    assert result.exit_code == 0
    assert "candidate_count=842" in result.stdout
    assert "shard_count=17" in result.stdout
    assert len(tuple((tmp_path / "cninfo_bridge_selections").glob("*/manifest.json"))) == 1
    assert len(tuple((tmp_path / "cninfo_full_discovery_plans").glob("*/manifest.json"))) == 1


def test_run_shard_cli_uses_only_exact_planned_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an explicit two-candidate selection and one exact shard plan.
    candidates = tuple(_candidate(index) for index in range(842))
    selection = freeze_full_candidate_selection(candidates)
    plan = build_full_discovery_plan(
        selection,
        shard_size=2,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    selection_path = tmp_path / "selection.json"
    plan_path = tmp_path / "plan.json"
    selection_path.write_text(selection.model_dump_json(), encoding="utf-8")
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    calls: list[str] = []

    def discover(
        _provider: str,
        candidate: OfficialBridgeCandidate,
        *,
        discovered_at: datetime,
    ) -> CninfoListingDiscoveryAudit:
        calls.append(candidate.symbol)
        return _missing_discovery(candidate, discovered_at)

    monkeypatch.setattr(cninfo_full_discovery_cli, "create_provider_client", Http)
    monkeypatch.setattr(cninfo_full_discovery_cli, "CninfoArchiveClient", lambda _h, _p: "provider")
    monkeypatch.setattr(cninfo_full_discovery_cli, "discover_cninfo_listing", discover)

    # When: only shard zero is executed.
    result = CliRunner().invoke(
        cninfo_full_discovery_cli.app,
        [
            "run-shard",
            "--selection",
            str(selection_path),
            "--plan",
            str(plan_path),
            "--shard-index",
            "0",
            "--output-root",
            str(tmp_path),
        ],
    )

    # Then: exact planned keys run once and one durable shard is produced.
    assert result.exit_code == 0
    assert calls == [item.symbol for item in selection.selected[:2]]
    assert "selected=0 missing=2" in result.stdout
    assert len(tuple((tmp_path / "cninfo_full_discovery_shards").glob("*/manifest.json"))) == 1


def _candidate(index: int) -> OfficialBridgeCandidate:
    return OfficialBridgeCandidate(
        symbol=f"{301001 + index:06d}.SZ",
        listing_date=datetime(
            2022,
            (index % 12) + 1,
            (index % 27) + 1,
            tzinfo=UTC,
        ).date(),
        source_event_ids=(f"event-{index}",),
        universe_schema_manifest_id=f"schema_{'a' * 64}",
        event_type="LISTED",
        quality_status="ACCEPTED",
    )


def _missing_discovery(
    candidate: OfficialBridgeCandidate,
    discovered_at: datetime,
) -> CninfoListingDiscoveryAudit:
    return CninfoListingDiscoveryAudit(
        audit_id=f"cninfo_listing_discovery_{candidate.symbol[:6] * 10}0000",
        audit_version="cninfo_listing_discovery_v1",
        discovered_at=discovered_at,
        candidate=candidate,
        status=CninfoDiscoveryStatus.MISSING,
        failure_reason="final_listing_announcement_missing",
        evidence=None,
        research_use_authorized=False,
    )
