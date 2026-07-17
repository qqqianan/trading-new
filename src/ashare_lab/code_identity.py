"""Shared Git identity adapter for reproducible lineage and research manifests."""

import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final

_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class GitEvidence:
    """Current full commit and worktree cleanliness."""

    commit: str
    is_clean: bool


@unique
class CodeIdentityFailure(StrEnum):
    """Closed reasons a Git identity cannot be issued."""

    EXECUTABLE_MISSING = "executable_missing"
    INVALID_COMMIT = "invalid_commit"
    COMMAND_FAILED = "command_failed"


class CodeIdentityError(Exception):
    """The current code cannot be bound to a real Git commit."""

    __slots__ = ("failure",)

    def __init__(self, failure: CodeIdentityFailure) -> None:
        """Create a fail-closed Git identity error."""
        super().__init__()
        self.failure = failure

    @property
    def detail(self) -> str:
        """Return actionable text without accepting arbitrary error strings."""
        match self.failure:
            case CodeIdentityFailure.EXECUTABLE_MISSING:
                return "Git executable not found"
            case CodeIdentityFailure.INVALID_COMMIT:
                return "Git did not return a full lowercase commit"
            case CodeIdentityFailure.COMMAND_FAILED:
                return "project does not have a readable Git identity"

    def __str__(self) -> str:
        """Return a stable rule and actionable detail."""
        return f"git_identity: {self.detail}"


def load_git_commit(project_root: Path) -> str:
    """Return the full commit used by one lineage write."""
    return load_git_evidence(project_root).commit


def load_git_evidence(project_root: Path) -> GitEvidence:
    """Read the current commit and worktree status through an absolute Git executable."""
    executable = shutil.which("git")
    if executable is None:
        raise CodeIdentityError(CodeIdentityFailure.EXECUTABLE_MISSING)
    commit = _run_git(executable, project_root, "rev-parse", "HEAD")
    if _COMMIT_PATTERN.fullmatch(commit) is None:
        raise CodeIdentityError(CodeIdentityFailure.INVALID_COMMIT)
    status = _run_git(executable, project_root, "status", "--porcelain")
    return GitEvidence(commit, status == "")


def _run_git(executable: str, project_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 - executable is resolved to an absolute path.
            (executable, "-C", str(project_root), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise CodeIdentityError(CodeIdentityFailure.COMMAND_FAILED) from error
    return completed.stdout.strip()
