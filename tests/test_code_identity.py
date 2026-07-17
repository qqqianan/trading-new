from pathlib import Path

import pytest

from ashare_lab.code_identity import CodeIdentityError, load_git_commit

PROJECT_ROOT = Path(__file__).parents[1]


def test_code_identity_loads_the_real_full_git_commit() -> None:
    # Given: the initialized governed project repository.
    # When: lineage requests the current code identity.
    commit = load_git_commit(PROJECT_ROOT)

    # Then: downstream evidence receives a full lowercase Git SHA.
    assert len(commit) == 40
    assert commit.isalnum()
    assert commit == commit.lower()


def test_code_identity_rejects_a_directory_without_git(tmp_path: Path) -> None:
    # Given: a directory outside any Git worktree.
    # When / Then: lineage generation fails closed instead of using a placeholder.
    with pytest.raises(CodeIdentityError, match="git_identity"):
        load_git_commit(tmp_path)
