import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ashare_lab.cninfo_full_discovery_cli import app
from ashare_lab.data.cninfo_listing_discovery import CninfoDiscoveryStatus
from ashare_lab.services.cninfo_bridge_sampling import StratifiedCandidateSelection
from ashare_lab.services.cninfo_discovery_coverage import build_discovery_coverage
from ashare_lab.services.cninfo_full_discovery import (
    CninfoFullDiscoveryError,
    CninfoFullDiscoveryPlan,
    CninfoFullDiscoveryShard,
    build_full_discovery_plan,
    build_full_discovery_shard,
    freeze_full_candidate_selection,
)
from tests.test_cninfo_full_discovery import _candidate, _discovery


def _inputs() -> tuple[
    StratifiedCandidateSelection, CninfoFullDiscoveryPlan, tuple[CninfoFullDiscoveryShard, ...]
]:
    selection = freeze_full_candidate_selection(tuple(_candidate(i) for i in range(842)))
    moment = datetime(2026, 9, 7, tzinfo=UTC)
    plan = build_full_discovery_plan(selection, shard_size=421, planned_at=moment)
    shards = []
    for index in range(2):
        audits = []
        for candidate in selection.selected[index * 421 : (index + 1) * 421]:
            audit = _discovery(candidate, CninfoDiscoveryStatus.MISSING)
            payload = json.dumps(
                audit.model_dump(mode="json", exclude={"audit_id"}),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            audit = audit.model_copy(
                update={
                    "audit_id": "cninfo_listing_discovery_"
                    + hashlib.sha256(payload.encode()).hexdigest()
                }
            )
            audits.append(audit)
        shards.append(
            build_full_discovery_shard(
                plan,
                selection,
                shard_index=index,
                audits=tuple(audits),
                completed_at=moment,
            )
        )
    return selection, plan, tuple(shards)


def test_complete_discovery_retains_all_failed_candidates_without_research_permission() -> None:
    # Given: every planned candidate has a persisted missing observation.
    selection, plan, shards = _inputs()

    # When: complete discovery coverage is evaluated.
    report = build_discovery_coverage(selection, plan, shards)

    # Then: operational completeness does not imply source quality or research admission.
    assert report.status == "COMPLETE_DISCOVERY"
    assert report.observed_count == report.missing_count == 842
    assert report.selected_count == 0
    assert len(report.failures) == 842
    assert report.research_use_authorized is False


def test_missing_shard_reports_incomplete_population() -> None:
    # Given: only the first half of a fixed plan was completed.
    selection, plan, shards = _inputs()

    # When: partial coverage is evaluated.
    report = build_discovery_coverage(selection, plan, shards[:1])

    # Then: the absent shard and population remain visible.
    assert report.status == "INCOMPLETE_DISCOVERY"
    assert report.missing_shard_indices == (1,)
    assert report.unobserved_count == 421


@pytest.mark.parametrize(
    "mutation", ["duplicate", "count", "lineage", "plan", "audit_hash", "version", "selection"]
)
def test_discovery_coverage_rejects_crossed_or_tampered_evidence(mutation: str) -> None:
    # Given: otherwise valid evidence with one changed parent, count, or identity.
    selection, plan, shards = _inputs()
    if mutation == "duplicate":
        shards = (shards[0], shards[0])
    elif mutation == "count":
        shards = (
            shards[0].model_copy(update={"selected_count": 421, "missing_count": 0}),
            shards[1],
        )
    elif mutation == "plan":
        plan = plan.model_copy(update={"shard_size": 400})
    elif mutation == "selection":
        selection = selection.model_copy(update={"candidate_universe_sha256": "f" * 64})
    else:
        audit = shards[0].audits[0]
        if mutation == "lineage":
            candidate = audit.candidate.model_copy(update={"source_event_ids": ("crossed",)})
            audit = audit.model_copy(update={"candidate": candidate})
        elif mutation == "version":
            audit = audit.model_copy(update={"audit_version": "unsupported"})
        else:
            audit = audit.model_copy(update={"audit_id": "cninfo_listing_discovery_" + "f" * 64})
        changed = build_full_discovery_shard(
            plan,
            selection,
            shard_index=0,
            audits=(audit, *shards[0].audits[1:]),
            completed_at=shards[0].completed_at,
        )
        shards = (changed, shards[1])

    # When / Then: altered evidence fails closed instead of producing a complete report.
    with pytest.raises(CninfoFullDiscoveryError):
        build_discovery_coverage(selection, plan, shards)


def test_coverage_cli_persists_report_from_only_explicit_shards(tmp_path: Path) -> None:
    # Given: explicit parent files and one supplied shard, despite another file being present.
    selection, plan, shards = _inputs()
    selection_path = tmp_path / "selection.json"
    plan_path = tmp_path / "plan.json"
    shard_path = tmp_path / "shard.json"
    selection_path.write_text(selection.model_dump_json(), encoding="utf-8")
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    shard_path.write_text(shards[0].model_dump_json(), encoding="utf-8")
    (tmp_path / "unused.json").write_text(shards[1].model_dump_json(), encoding="utf-8")

    # When: the operator requests coverage using only the explicitly supplied shard.
    result = CliRunner().invoke(
        app,
        [
            "coverage",
            "--selection",
            str(selection_path),
            "--plan",
            str(plan_path),
            "--shard",
            str(shard_path),
            "--output-root",
            str(tmp_path / "reports"),
        ],
    )

    # Then: the unlisted file cannot silently complete coverage.
    assert result.exit_code == 0, result.output
    assert "INCOMPLETE_DISCOVERY" in result.output
    assert "observed=421" in result.output
    assert len(tuple((tmp_path / "reports").glob("*/manifest.json"))) == 1
