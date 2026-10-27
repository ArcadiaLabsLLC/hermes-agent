"""Agent authoring on a git course: the course's checkout, and commits on an authoring branch.

Plan: ``docs/agent-runtime-harness/planned/realm-course-subject-authoring-2026-10-21.md`` (stages C1–C3).
C3's pull request needs ``pull_requests: write`` on the course App (``RT-COURSE-AUTHORING-RULINGS``); until
the App carries it GitHub answers 403 and the verb refuses ``pull_request_not_permitted`` — the branch is
pushed, and the author opens the PR by hand.

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
``course.commit {course, branch, sha, files}``, ``course.pull_request {course, branch, number}``.
RPC: ``serve_rpc/course.py``.
"""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from . import paths
from .git_cmd import run_git

if TYPE_CHECKING:  # the realm lane loads on the first verb, not with the method table
    from .realm_membership import RealmSyncCredential

__layer__ = "stores"
__all__ = [
    "CheckoutReceipt",
    "CommitReceipt",
    "CourseRefusal",
    "CourseRefused",
    "PullRequestReceipt",
    "VERB_LOCK",
    "admit",
    "checkout",
    "commit",
    "parse_credential",
    "pull_request",
]

#: Course verbs run one at a time in a process (``runtime.course.*`` and the persona tools share it): two
#: verbs never share a clone at once.
VERB_LOCK = threading.Lock()

_TAIL = 400
_EMPTY_REMOTE = "couldn't find remote ref"
_FALLBACK_BRANCH = "main"
#: A persona id and a branch slug: one path segment each (``agent/<persona_id>/<slug>``).
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REJECTED_PUSH = ("[rejected]", "non-fast-forward", "fetch first")
_AGENT_EMAIL_DOMAIN = "eternia.agents"


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
    PATH_INVALID = "course_path_invalid"
    NOTHING_TO_COMMIT = "course_nothing_to_commit"
    COMMIT_FAILED = "commit_failed"
    PUSH_FAILED = "push_failed"
    HOST_UNSUPPORTED = "git_host_unsupported"
    PR_NOT_PERMITTED = "pull_request_not_permitted"
    BRANCH_NOT_PUSHED = "course_branch_not_pushed"
    PR_FAILED = "pull_request_failed"


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


@dataclass(frozen=True)
class CommitReceipt:
    course: str
    branch: str
    sha: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class PullRequestReceipt:
    course: str
    branch: str
    number: int
    html_url: str
    existing: bool


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


# ── C2: a commit on an authoring branch ──────────────────────────────────────


def _contained(relative: object) -> str:
    """A repo-relative POSIX path, refused when it leaves the repo or names git's own tree
    (``work_store.writer.Writer._write_files``'s rule)."""

    text = str(relative or "").replace("\\", "/").strip()
    path = PurePosixPath(text)
    if not text or path.is_absolute() or re.match(r"^[A-Za-z]:", text):
        raise CourseRefused(CourseRefusal.PATH_INVALID, f"{text!r} is not a repo-relative path")
    if ".." in path.parts or path.parts[0] == ".git":
        raise CourseRefused(CourseRefusal.PATH_INVALID, f"{text!r} leaves the course repo")
    return path.as_posix()


def _segment(value: str, name: str) -> str:
    if not _SEGMENT.match(value or ""):
        raise CourseRefused(CourseRefusal.INVALID_REQUEST, f"{name} must be one segment of [A-Za-z0-9._-]")
    return value


def _origin_head(git: _Git, repo: Path) -> str:
    """The default branch ``checkout`` recorded as ``refs/remotes/origin/HEAD``."""

    found = git.call(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    branch = str(found.stdout or "").strip().removeprefix("origin/")
    if found.returncode != 0 or not branch:
        raise CourseRefused(CourseRefusal.NOT_CHECKED_OUT, "the course has no default branch yet; check it out")
    return branch


def _fetch_branch(git: _Git, repo: Path, branch: str) -> bool:
    """Fetch ``branch`` into ``origin/<branch>``; False when the remote does not carry it."""

    done = git.authed(repo, "fetch", "-q", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    if done.returncode == 0:
        return True
    if _EMPTY_REMOTE in str(done.stderr or ""):
        return False
    raise CourseRefused(CourseRefusal.FETCH_FAILED, f"git fetch: {git.scrub(done.stderr)}")


def _ensure_worktree(git: _Git, repo: Path, worktree: Path, branch: str, base: str) -> None:
    """The branch's worktree beside the clone (``batch.lane_git.LaneGit.ensure``'s shape); a reused one is
    reset to its HEAD — what a failed earlier verb left uncommitted is not this call's."""

    git.call(repo, "worktree", "prune")
    if (worktree / ".git").exists():
        git.must(CourseRefusal.WORKTREE_FAILED, worktree, "reset", "-q", "--hard", "HEAD")
        return
    if worktree.exists() and any(worktree.iterdir()):
        raise CourseRefused(CourseRefusal.WORKTREE_FAILED, "the branch's worktree exists and is not a worktree")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if git.ok(repo, "rev-parse", "-q", "--verify", f"refs/heads/{branch}"):
        args = ["worktree", "add", "-q", str(worktree), branch]
    else:
        args = ["worktree", "add", "-q", "--no-track", "-b", branch, str(worktree), base]
    git.must(CourseRefusal.WORKTREE_FAILED, repo, *args)


def _catch_up(git: _Git, worktree: Path, remote_tip: str) -> None:
    """Fast-forward onto the pushed branch, or keep a local lead; two histories refuse."""

    if git.ok(worktree, "merge-base", "--is-ancestor", remote_tip, "HEAD"):
        return
    if git.ok(worktree, "merge-base", "--is-ancestor", "HEAD", remote_tip):
        git.must(CourseRefusal.BRANCH_DIVERGED, worktree, "merge", "-q", "--ff-only", remote_tip)
        return
    raise CourseRefused(CourseRefusal.BRANCH_DIVERGED, f"{remote_tip} and the local branch have diverged")


def _stage(git: _Git, worktree: Path, files: Mapping[str, str], deletes: Sequence[str]) -> list[str]:
    """Write ``files`` and remove ``deletes`` in the worktree, staged; the paths touched, sorted."""

    for relative, body in files.items():
        target = worktree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(str(body).encode("utf-8"))
    if files:
        git.must(CourseRefusal.COMMIT_FAILED, worktree, "add", "--", *files)
    if deletes:
        git.must(CourseRefusal.COMMIT_FAILED, worktree, "rm", "-q", "--ignore-unmatch", "--", *deletes)
    return sorted({*files, *deletes})


def _push(git: _Git, worktree: Path, branch: str) -> None:
    """``push -u origin <branch>`` — never forced; a rejected push is ``course_branch_diverged``."""

    done = git.authed(worktree, "push", "-u", "origin", branch)
    if done.returncode != 0:
        stderr = str(done.stderr or "")
        rejected = any(marker in stderr for marker in _REJECTED_PUSH)
        raise CourseRefused(CourseRefusal.BRANCH_DIVERGED if rejected else CourseRefusal.PUSH_FAILED,
                            f"git push: {git.scrub(stderr)}")


def commit(credential: RealmSyncCredential, *, persona_id: str, branch: str, message: str,
           files: Mapping[str, str], deletes: Sequence[str] = (), persona_name: str | None = None,
           run: Callable[..., subprocess.CompletedProcess[str]] = run_git) -> CommitReceipt:
    """One commit on ``agent/<persona_id>/<branch>``, authored by the persona, pushed (never forced).

    The branch is cut from ``origin/<default branch>`` (or continues the pushed branch) in a worktree under
    ``paths.course_worktrees_dir``; ``files`` are written and ``deletes`` removed, each contained under the
    repo root (``course_path_invalid``). A pushed branch that moved under it refuses ``course_branch_diverged``.
    """

    from .work_store.receipts import emit

    course = admit(credential)
    full = f"agent/{_segment(persona_id, 'persona_id')}/{_segment(branch, 'branch')}"
    text = str(message or "").strip()
    if not text:
        raise CourseRefused(CourseRefusal.INVALID_REQUEST, "message is required")
    files = {_contained(path): body for path, body in (files or {}).items()}
    deletes = [_contained(path) for path in deletes or ()]
    if not files and not deletes:
        raise CourseRefused(CourseRefusal.INVALID_REQUEST, "files or deletes is required")
    git = _Git(credential, run)
    repo = paths.course_checkout_dir(course)
    if not (repo / ".git").exists():
        raise CourseRefused(CourseRefusal.NOT_CHECKED_OUT, "check the course out first")
    if str(git.call(repo, "config", "--get", "remote.origin.url").stdout or "").strip() != credential.git_url:
        raise CourseRefused(CourseRefusal.URL_MISMATCH, "the course clone's origin names another remote")
    default = _origin_head(git, repo)
    _fetch_branch(git, repo, default)
    pushed = _fetch_branch(git, repo, full)
    worktree = paths.course_worktrees_dir(course) / paths.safe_path_token(full)
    _ensure_worktree(git, repo, worktree, full, f"origin/{full}" if pushed else f"origin/{default}")
    if pushed:
        _catch_up(git, worktree, f"origin/{full}")
    touched = _stage(git, worktree, files, deletes)
    if git.ok(worktree, "diff", "--cached", "--quiet"):
        raise CourseRefused(CourseRefusal.NOTHING_TO_COMMIT, "the files already read that way")
    name = " ".join(str(persona_name or "").split())[:80] or persona_id
    author = (f"user.name={name}", f"user.email={persona_id}@{_AGENT_EMAIL_DOMAIN}", "commit.gpgsign=false")
    git.must(CourseRefusal.COMMIT_FAILED, worktree, "commit", "-q", "--no-verify", "-m", text, config=author)
    sha = git.must(CourseRefusal.COMMIT_FAILED, worktree, "rev-parse", "HEAD")
    _push(git, worktree, full)
    emit("course.commit", course=course, branch=full, sha=sha, files=touched)
    return CommitReceipt(course, full, sha, tuple(touched))


# ── C3: the pull request ─────────────────────────────────────────────────────

_GITHUB_REMOTE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_PR_TITLE_LIMIT = 256
_PR_BODY_LIMIT = 60_000
#: GitHub statuses that mean "the installation token may not open a PR here": the App lacks
#: ``pull_requests: write`` (403), or the token cannot see the repo at all (404).
_NOT_PERMITTED = (401, 403, 404)

#: ``(method, path, authorization, body) -> (status, json)`` — ``git_host_account.github_request``'s shape.
Request = Callable[..., "tuple[int, object]"]


def _github_repo(git_url: str) -> tuple[str, str]:
    """``(owner, repo)`` of a GitHub HTTPS remote; any other host refuses ``git_host_unsupported``."""

    found = _GITHUB_REMOTE.match(str(git_url or "").strip())
    if not found:
        raise CourseRefused(CourseRefusal.HOST_UNSUPPORTED, "the course remote is not a github.com HTTPS remote")
    return found.group(1), found.group(2)


def _github_request() -> Request:
    from .git_host_account import github_request

    return github_request


def _refused_status(status: int, verb: str) -> CourseRefused:
    if status in _NOT_PERMITTED:
        return CourseRefused(CourseRefusal.PR_NOT_PERMITTED,
                             f"GitHub answered {status} to {verb}; the course App needs pull_requests: write")
    if status == 422:
        return CourseRefused(CourseRefusal.BRANCH_NOT_PUSHED,
                             "GitHub refused the pull request (422): push the branch with a commit first")
    return CourseRefused(CourseRefusal.PR_FAILED, f"GitHub answered {status} to {verb}")


def pull_request(credential: RealmSyncCredential, *, persona_id: str, branch: str, title: str, body: str = "",
                 base: str | None = None, request: Request | None = None) -> PullRequestReceipt:
    """Open — or answer the already-open — pull request for ``agent/<persona_id>/<branch>``.

    ``base`` is the course's default branch (``checkout`` records it as ``origin/HEAD``) unless given. An open
    PR whose head is the branch is answered without a POST (``existing``). The credential's
    ``git_authorization`` is the ``Authorization`` header and never reaches the receipt, a refusal or a log.
    """

    from .work_store.receipts import emit

    course = admit(credential)
    full = f"agent/{_segment(persona_id, 'persona_id')}/{_segment(branch, 'branch')}"
    heading = " ".join(str(title or "").split())[:_PR_TITLE_LIMIT]
    if not heading:
        raise CourseRefused(CourseRefusal.INVALID_REQUEST, "title is required")
    owner, repo_name = _github_repo(credential.git_url)
    if base is None:
        repo = paths.course_checkout_dir(course)
        if not (repo / ".git").exists():
            raise CourseRefused(CourseRefusal.NOT_CHECKED_OUT, "check the course out first")
        base = _origin_head(_Git(credential, run_git), repo)
    call = request or _github_request()
    authorization = credential.git_authorization
    pulls = f"/repos/{owner}/{repo_name}/pulls"
    try:
        admit(credential)
        status, found = call("GET", f"{pulls}?state=open&head={owner}:{full}", authorization)
        if status != 200 or not isinstance(found, list):
            raise _refused_status(status, "the open-PR lookup")
        if found:
            hit = found[0]
            emit("course.pull_request", course=course, branch=full, number=int(hit["number"]))
            return PullRequestReceipt(course, full, int(hit["number"]), str(hit.get("html_url") or ""), True)
        admit(credential)
        status, made = call("POST", pulls, authorization,
                            {"title": heading, "head": full, "base": base, "body": str(body or "")[:_PR_BODY_LIMIT]})
    except OSError as exc:
        raise CourseRefused(CourseRefusal.PR_FAILED, f"GitHub unreachable: {type(exc).__name__}") from None
    if status != 201 or not isinstance(made, dict) or not isinstance(made.get("number"), int):
        raise _refused_status(status, "the pull request")
    emit("course.pull_request", course=course, branch=full, number=made["number"])
    return PullRequestReceipt(course, full, made["number"], str(made.get("html_url") or ""), False)
