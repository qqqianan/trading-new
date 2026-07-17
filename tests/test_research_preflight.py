from pathlib import Path

import pytest

from ashare_lab.research.preflight import (
    GitEvidence,
    PreflightRequest,
    ResearchPreflightError,
    assess_research_preflight,
    run_research_preflight,
)

PROJECT_ROOT = Path(__file__).parents[1]


def test_preflight_builds_identity_from_the_real_repository() -> None:
    # Given: the governed project root and its isolated research database.
    request = PreflightRequest(
        project_root=PROJECT_ROOT,
        database_name="ashare_quant",
        require_clean_worktree=False,
    )

    # When: the research identity preflight reads immutable project evidence.
    identity = run_research_preflight(request)

    # Then: the result binds a real commit, dependency lock, and rulebook version.
    assert len(identity.git_commit) == 40
    assert len(identity.uv_lock_sha256) == 64
    assert identity.rulebook_version == "1.1.0"
    assert identity.database_name == "ashare_quant"


def test_preflight_rejects_a_dirty_worktree_for_reproducible_work() -> None:
    # Given: valid identities but uncommitted project state.
    request = PreflightRequest(Path(), "ashare_quant", require_clean_worktree=True)
    git = GitEvidence(commit="a" * 40, is_clean=False)

    # When / Then: the fail-closed assessment refuses the dirty identity.
    with pytest.raises(ResearchPreflightError, match="dirty_worktree"):
        assess_research_preflight(request, git, "b" * 64)


def test_preflight_rejects_the_legacy_database() -> None:
    # Given: a request pointed at an ungoverned database.
    request = PreflightRequest(Path(), "legacy", require_clean_worktree=False)
    git = GitEvidence(commit="a" * 40, is_clean=True)

    # When / Then: no research identity can be issued for that source.
    with pytest.raises(ResearchPreflightError, match="database_isolation"):
        assess_research_preflight(request, git, "b" * 64)


def test_preflight_rejects_a_directory_without_git_identity(tmp_path: Path) -> None:
    # Given: a directory with a dependency lock but no Git repository.
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    request = PreflightRequest(tmp_path, "ashare_quant", require_clean_worktree=False)

    # When / Then: Git absence is reported as a typed governance failure.
    with pytest.raises(ResearchPreflightError, match="git_identity"):
        run_research_preflight(request)
