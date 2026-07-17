"""Fail-closed project identity checks for reproducible research artifacts."""

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final

from ashare_lab.code_identity import CodeIdentityError, GitEvidence, load_git_evidence

_RULEBOOK_VERSION: Final = "1.1.0"
_GOVERNED_DATABASE: Final = "ashare_quant"
_GIT_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


@unique
class PreflightRule(StrEnum):
    """Stable rejection codes emitted by the research identity gate."""

    DATABASE_ISOLATION = "database_isolation"
    DIRTY_WORKTREE = "dirty_worktree"
    GIT_IDENTITY = "git_identity"
    DEPENDENCY_LOCK = "dependency_lock"


@dataclass(frozen=True, slots=True)
class PreflightRequest:
    """Project boundary and reproducibility level requested by a workflow."""

    project_root: Path
    database_name: str
    require_clean_worktree: bool


@dataclass(frozen=True, slots=True)
class ResearchIdentity:
    """Immutable engineering evidence referenced by downstream artifacts."""

    git_commit: str
    uv_lock_sha256: str
    rulebook_version: str
    database_name: str


class ResearchPreflightError(Exception):
    """Research cannot issue a reproducible project identity."""

    __slots__ = ("detail", "rule")

    def __init__(self, rule: PreflightRule, detail: str) -> None:
        """Create a typed rejection with a stable machine-readable rule."""
        super().__init__()
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        """Return the stable rule followed by actionable detail."""
        return f"{self.rule.value}: {self.detail}"


def run_research_preflight(request: PreflightRequest) -> ResearchIdentity:
    """Read Git and dependency evidence before assessing research eligibility."""
    try:
        git = load_git_evidence(request.project_root)
    except CodeIdentityError as error:
        raise ResearchPreflightError(PreflightRule.GIT_IDENTITY, error.detail) from error
    lock_digest = _load_lock_digest(request.project_root / "uv.lock")
    return assess_research_preflight(request, git, lock_digest)


def assess_research_preflight(
    request: PreflightRequest,
    git: GitEvidence,
    uv_lock_sha256: str,
) -> ResearchIdentity:
    """Issue an identity only when every engineering boundary is explicit."""
    if request.database_name != _GOVERNED_DATABASE:
        raise ResearchPreflightError(
            PreflightRule.DATABASE_ISOLATION,
            f"research database must be {_GOVERNED_DATABASE}",
        )
    if _GIT_COMMIT_PATTERN.fullmatch(git.commit) is None:
        raise ResearchPreflightError(
            PreflightRule.GIT_IDENTITY,
            "Git commit must be a full lowercase SHA-1",
        )
    if request.require_clean_worktree and not git.is_clean:
        raise ResearchPreflightError(
            PreflightRule.DIRTY_WORKTREE,
            "reproducible research requires a clean worktree",
        )
    if _SHA256_PATTERN.fullmatch(uv_lock_sha256) is None:
        raise ResearchPreflightError(
            PreflightRule.DEPENDENCY_LOCK,
            "uv.lock digest must be a lowercase SHA-256",
        )
    return ResearchIdentity(
        git_commit=git.commit,
        uv_lock_sha256=uv_lock_sha256,
        rulebook_version=_RULEBOOK_VERSION,
        database_name=request.database_name,
    )


def _load_lock_digest(path: Path) -> str:
    try:
        with path.open("rb") as lock_file:
            content = lock_file.read()
    except FileNotFoundError as error:
        raise ResearchPreflightError(
            PreflightRule.DEPENDENCY_LOCK,
            "uv.lock is missing",
        ) from error
    return hashlib.sha256(content).hexdigest()
