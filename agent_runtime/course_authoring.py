"""Agent authoring on a git course: the course's checkout, and commits on an authoring branch.

Plan: ``docs/agent-runtime-harness/planned/realm-course-subject-authoring-2026-10-21.md`` (stages C1–C2;
C3, the pull request, waits on ``RT-COURSE-AUTHORING-RULINGS``).

**A course is a checkout under the store root, never a slot and never a realm.**
``paths.course_checkout_dir(course_public_id)`` holds one clone per course per machine; authoring branches
get worktrees beside it (``paths.course_worktrees_dir``). The backend-minted ``course:<id>`` credential
(``RealmSyncCredential``, schema v1) arrives INLINE from the caller for each verb, is held in memory for the
verb's duration only, and rides every network git call as ``-c http.extraHeader=…`` pairs — never
``.git/config``, never a receipt, never a log line; refusal text is scrubbed of it. Its ``expires_at`` is
checked before each network step (``course_credential_expired``: the Launcher re-brokers).

Only a COURSE credential is admitted (``credential_subject_mismatch`` otherwise): a realm credential cannot
author a course, and ``realm_sync`` already refuses a course credential.

Receipts (``work_store.receipts.emit``; no envelope keys): ``course.checkout {course, outcome, branch}``,
``course.commit {course, branch, sha, files}``. RPC: ``serve_rpc/course.py``.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from . import paths
from .git_cmd import run_git

if TYPE_CHECKING:  # the realm lane loads on the first verb, not with the method table
    from .realm_membership import RealmSyncCredential

__layer__ = "stores"
__all__ = [
    "CheckoutReceipt",
    "CourseRefusal",
    "CourseRefused",
    "admit",
    "checkout",
    "parse_credential",
]

_TAIL = 400
_EMPTY_REMOTE = "couldn't find remote ref"
_FALLBACK_BRANCH = "main"


class CourseRefusal(StrEnum):
    """Every ``reason`` a course verb refuses with (the RPC's ``data.reason``)."""

    INVALID_REQUEST = "invalid_request"
    CREDENTIAL_INVALID = "course_credential_invalid"
    CREDENTIAL_EXPIRED = "course_credential_expired"
    SUBJECT_MISMATCH = "credential_subject_mismatch"
    NOT_CHECKED_OUT = "course_not_checked_out"
    URL_MISMATCH = "url_mismatch"
    FETCH_FAILED = "fetch_failed"
    BRANCH_DIVERGED = "course_branch_diverged"
    WORKTREE_FAILED = "worktree_failed"


class CourseRefused(ValueError):
    def __init__(self, reason: CourseRefusal, detail: str = "") -> None:
        super().__init__(detail or reason.value)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class CheckoutReceipt:
    course: str
    outcome: str
    branch: str
    head: str
    path: Path


#: ``git_remote_adopt.AdoptRefused.reason`` -> the course refusal it is.
_ADOPT_REASONS: dict[str, CourseRefusal] = {
    "url_mismatch": CourseRefusal.URL_MISMATCH,
    "remote_diverged": CourseRefusal.BRANCH_DIVERGED,
    "fetch_failed": CourseRefusal.FETCH_FAILED,
    "not_a_repo": CourseRefusal.WORKTREE_FAILED,
}


def parse_credential(raw: object) -> RealmSyncCredential:
    """The inline credential, by the realm lane's own parser; an expired one is ``course_credential_expired``."""

    from .realm_membership import RealmSyncCredential
    from .realm_sync import RealmSyncError

    try:
        return RealmSyncCredential.parse(raw)
    except RealmSyncError as exc:
        expired = "expires_at" in exc.safe_details
        raise CourseRefused(CourseRefusal.CREDENTIAL_EXPIRED if expired else CourseRefusal.CREDENTIAL_INVALID,
                            str(exc)) from None


def admit(credential: RealmSyncCredential) -> str:
    """The course id a credential authorizes; refused for any other subject, or once expired."""

    from .realm_membership import CredentialSubject

    if credential.subject is not CredentialSubject.COURSE:
        raise CourseRefused(CourseRefusal.SUBJECT_MISMATCH,
                            f"credential was issued for a {credential.subject.value}, not a course")
    if credential.is_expired():
        raise CourseRefused(CourseRefusal.CREDENTIAL_EXPIRED, "course credential expired; re-broker it")
    return credential.subject_id


@dataclass(frozen=True)
class _Git:
    """One verb's git: ``authed`` calls carry the credential's ``-c`` pairs, every other call none."""

    credential: RealmSyncCredential
    run: Callable[..., subprocess.CompletedProcess[str]]

    @property
    def auth(self) -> tuple[str, ...]:
        return tuple(self.credential.git_extra_config())

    def call(self, repo: Path, *args: str, config: Sequence[str] = ()) -> subprocess.CompletedProcess[str]:
        return self.run(list(args), repo=repo, config=tuple(config), encoding="utf-8", errors="replace",
                        timeout=300, stdin=subprocess.DEVNULL)

    def authed(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        admit(self.credential)  # expiry, at every network step
        return self.call(repo, *args, config=self.auth)

    def scrub(self, text: object) -> str:
        from .realm_sync.git import _scrub_config_values

        secret = f"x={self.credential.git_authorization}"
        return _scrub_config_values(str(text or ""), (*self.auth, secret)).strip()[-_TAIL:]

    def must(self, reason: CourseRefusal, repo: Path, *args: str, config: Sequence[str] = ()) -> str:
        done = self.call(repo, *args, config=config)
        if done.returncode != 0:
            raise CourseRefused(reason, f"git {args[0]}: {self.scrub(done.stderr)}")
        return str(done.stdout or "").strip()

    def ok(self, repo: Path, *args: str) -> bool:
        return self.call(repo, *args).returncode == 0


def _remote_default_branch(git: _Git, repo: Path) -> str:
    """The remote's HEAD branch (``ls-remote --symref``); ``main`` for a remote with no HEAD yet."""

    done = git.authed(repo, "ls-remote", "--symref", git.credential.git_url, "HEAD")
    if done.returncode != 0:
        raise CourseRefused(CourseRefusal.FETCH_FAILED, f"git ls-remote: {git.scrub(done.stderr)}")
    found = re.search(r"^ref: refs/heads/(\S+)\s+HEAD$", str(done.stdout or ""), re.MULTILINE)
    return found.group(1) if found else _FALLBACK_BRANCH


def _course_dir_is_clone(repo: Path) -> bool:
    """True for an existing clone; False for a (now created) empty directory; refused for anything else."""

    if (repo / ".git").exists():
        return True
    if repo.exists() and any(repo.iterdir()):
        raise CourseRefused(CourseRefusal.WORKTREE_FAILED, "the course directory exists and is not a clone")
    repo.mkdir(parents=True, exist_ok=True)
    return False


def checkout(credential: RealmSyncCredential, *,
             run: Callable[..., subprocess.CompletedProcess[str]] = run_git) -> CheckoutReceipt:
    """Clone (or fetch) the course repo at its default branch into ``paths.course_checkout_dir``.

    ``adopt_remote`` does the reconcile: ``added_fetched`` into the empty clone, ``already`` thereafter (the
    clone's default branch then fast-forwards to the fetched tip); ``url_mismatch`` when the directory's
    ``origin`` is another repo.
    """

    from .git_remote_adopt import AdoptRefused, adopt_remote
    from .work_store.receipts import emit

    course = admit(credential)
    git = _Git(credential, run)
    repo = paths.course_checkout_dir(course)
    cloned = _course_dir_is_clone(repo)
    branch = _remote_default_branch(git, repo)
    if not cloned:
        git.must(CourseRefusal.WORKTREE_FAILED, repo, "init", "-q")
        git.must(CourseRefusal.WORKTREE_FAILED, repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    admit(credential)
    try:
        adopted = adopt_remote(repo, credential.git_url, branch=branch, config=git.auth, run=run)
    except AdoptRefused as exc:
        raise CourseRefused(_ADOPT_REASONS.get(exc.reason, CourseRefusal.FETCH_FAILED), git.scrub(exc.detail)) from None
    head = adopted.head
    if git.ok(repo, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}"):
        git.call(repo, "remote", "set-head", "origin", branch)  # local: the default branch commit() cuts from
        git.must(CourseRefusal.BRANCH_DIVERGED, repo, "merge", "-q", "--ff-only", f"origin/{branch}")
        head = git.must(CourseRefusal.WORKTREE_FAILED, repo, "rev-parse", "HEAD")
    emit("course.checkout", course=course, outcome=adopted.outcome.value, branch=branch)
    return CheckoutReceipt(course, adopted.outcome.value, branch, head, repo)
