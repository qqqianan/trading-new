from datetime import UTC, datetime
from pathlib import Path

import pytest

from ashare_lab.data.cninfo_listing_discovery import CninfoDiscoveryStatus
from ashare_lab.services.cninfo_full_discovery import (
    CninfoFullDiscoveryError,
    build_full_discovery_plan,
    build_full_discovery_shard,
    freeze_full_candidate_selection,
)
from ashare_lab.services.cninfo_full_discovery_artifacts import (
    CninfoFullDiscoveryArtifactError,
    write_full_discovery_plan,
    write_full_discovery_shard,
    write_listing_discovery_audit,
)
from tests.test_cninfo_full_discovery import _candidate, _discovery


def test_discovery_artifacts_are_immutable_recovery_units(tmp_path: Path) -> None:
    # Given: one exact plan, discovery observation, and completed shard.
    selection = freeze_full_candidate_selection(tuple(_candidate(index) for index in range(842)))
    plan = build_full_discovery_plan(
        selection,
        shard_size=2,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    audits = tuple(
        _discovery(candidate, CninfoDiscoveryStatus.MISSING) for candidate in selection.selected[:2]
    )
    shard = build_full_discovery_shard(
        plan,
        selection,
        shard_index=0,
        audits=audits,
        completed_at=datetime(2026, 9, 4, 1, tzinfo=UTC),
    )

    # When: every document is written and the exact plan is written again.
    plan_artifact = write_full_discovery_plan(plan, tmp_path / "plans")
    repeated = write_full_discovery_plan(plan, tmp_path / "plans")
    audit_artifact = write_listing_discovery_audit(audits[0], tmp_path / "audits")
    shard_artifact = write_full_discovery_shard(shard, tmp_path / "shards")

    # Then: exact bytes reuse one identity and all recovery units exist.
    assert repeated == plan_artifact
    assert audit_artifact.path.is_file()
    assert shard_artifact.path.is_file()


def test_discovery_artifact_rejects_conflicting_existing_bytes(tmp_path: Path) -> None:
    # Given: an exact plan path whose bytes are modified after publication.
    selection = freeze_full_candidate_selection(tuple(_candidate(index) for index in range(842)))
    plan = build_full_discovery_plan(
        selection,
        shard_size=50,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    artifact = write_full_discovery_plan(plan, tmp_path)
    artifact.path.write_text("conflict\n", encoding="utf-8")

    # When / Then: an immutable identity cannot silently accept different bytes.
    with pytest.raises(CninfoFullDiscoveryArtifactError, match="bytes differ"):
        write_full_discovery_plan(plan, tmp_path)


def test_full_discovery_rejects_partial_population_plan() -> None:
    # Given: one population missing a candidate.
    partial = freeze_full_candidate_selection(tuple(_candidate(index) for index in range(841)))

    # When / Then: partial planning cannot create a provider work list.
    with pytest.raises(CninfoFullDiscoveryError, match="exact 842-candidate"):
        build_full_discovery_plan(
            partial,
            shard_size=50,
            planned_at=datetime(2026, 9, 4, tzinfo=UTC),
        )


def test_full_discovery_rejects_out_of_range_shard() -> None:
    # Given: one valid 842-stock plan and its exact selection.
    complete = freeze_full_candidate_selection(tuple(_candidate(index) for index in range(842)))
    plan = build_full_discovery_plan(
        complete,
        shard_size=50,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    )

    # When / Then: an undefined recovery unit cannot execute.
    with pytest.raises(CninfoFullDiscoveryError, match="outside the plan"):
        build_full_discovery_shard(
            plan,
            complete,
            shard_index=len(plan.shards),
            audits=(),
            completed_at=datetime(2026, 9, 4, 1, tzinfo=UTC),
        )


def test_full_discovery_rejects_reordered_shard_audits() -> None:
    # Given: one valid plan with the first two observations reversed.
    selection = freeze_full_candidate_selection(tuple(_candidate(index) for index in range(842)))
    plan = build_full_discovery_plan(
        selection,
        shard_size=2,
        planned_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    audits = tuple(
        _discovery(candidate, CninfoDiscoveryStatus.MISSING)
        for candidate in reversed(selection.selected[:2])
    )

    # When / Then: caller ordering cannot redefine the planned candidate keys.
    with pytest.raises(CninfoFullDiscoveryError, match="audit keys"):
        build_full_discovery_shard(
            plan,
            selection,
            shard_index=0,
            audits=audits,
            completed_at=datetime(2026, 9, 4, 1, tzinfo=UTC),
        )
