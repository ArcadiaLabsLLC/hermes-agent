"""The git program's answers to the realm-sync port (``git_port.SyncGit``): today's argv, behind the verbs.

Each verb runs exactly the argv its call site ran before the port, through ``git._git`` /
``git.run_sync_git`` (the ``SYNC_IDENTITY`` and ``core.longpaths`` pairs, the identity
variables dropped, prompts off), and parses git's text HERE, so no caller reads git's
output again. A failing step raises the ``RealmSyncError`` ``_git`` always raised, with
the same ``git_args`` and scrubbed ``stderr``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .git import (
    _credential_git_config,
    _git,
    _git_clone,
    _git_failure,
    _push_was_rejected,
    _REPO_CONFIG,
    _scrub_config_values,
    _redact_text,
    run_sync_git,
)
from .git_port import ChangedPath, FetchOutcome, LogEntry, MergeOutcome, PushOutcome, PushReport, RepoState

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

__layer__ = "stores"
__all__ = ["BinarySyncGit"]

#: Separators ``git log --format`` writes between records and fields (ASCII RS / US),
#: which no sha, date or author name carries.
_RECORD, _FIELD = "\x1e", "\x1f"


class BinarySyncGit:
    """``git_port.SyncGit`` over the host's git program, for the clone at ``repo``."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)

    def _out(self, *args: str) -> str:
        return _git(self.repo, *args, check=False).strip()

    # -- the repository and its remotes ------------------------------------------------------
    def init(self) -> None:
        _git(self.repo, "init")

    def clone(self, url: str, auth: RealmSyncCredential | None) -> None:
        _git_clone(url, self.repo, extra_config=_credential_git_config(auth))

    def remote_url(self, name: str) -> str | None:
        return self._out("config", "--get", f"remote.{name}.url") or None

    def remotes(self) -> tuple[str, ...]:
        return tuple(_git(self.repo, "remote", check=False).split())

    def remote_add(self, name: str, url: str) -> None:
        _git(self.repo, "remote", "add", name, url)

    def remote_remove(self, name: str, *, missing_ok: bool = False) -> None:
        # git drops the remote's tracking refs with it.
        _git(self.repo, "remote", "remove", name, check=not missing_ok)

    def has_remote_refs(self) -> bool:
        return bool(self._out("for-each-ref", "--count=1", "refs/remotes"))

    # -- branches and refs -------------------------------------------------------------------
    def current_branch(self) -> str | None:
        return self._out("symbolic-ref", "--short", "-q", "HEAD") or None

    def rename_branch(self, branch: str) -> None:
        if self.resolve("HEAD"):
            _git(self.repo, "branch", "-M", branch)
        else:
            _git(self.repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")

    def resolve(self, ref: str) -> str | None:
        return self._out("rev-parse", "-q", "--verify", ref) or None

    def upstream(self) -> str | None:
        return self._out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") or None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return run_sync_git(("merge-base", "--is-ancestor", ancestor, descendant), repo=self.repo,
                            config=_REPO_CONFIG).returncode == 0

    # -- the working tree and the index ------------------------------------------------------
    def is_tracked(self, path: str) -> bool:
        return bool(self._out("ls-files", "--", path))

    def state(self) -> RepoState:
        conflicts = tuple(line.strip() for line in _git(self.repo, "diff", "--name-only", "--diff-filter=U", check=False).splitlines() if line.strip())
        ahead = behind = 0
        if self.upstream():
            counts = _git(self.repo, "rev-list", "--left-right", "--count", "HEAD...@{u}", check=False).split()
            if len(counts) == 2:
                ahead, behind = int(counts[0]), int(counts[1])
        elif self.remotes():
            # No upstream yet but a remote: commits no remote holds are waiting to be published.
            count = self._out("rev-list", "--count", "HEAD", "--not", "--remotes")
            ahead = int(count) if count.isdigit() else 0
        dirty = bool(self._out("status", "--porcelain"))
        return RepoState(ahead=ahead, behind=behind, conflicts=conflicts, dirty=dirty)

    def changed(self, paths: Sequence[str] = (), *, untracked_all: bool = False) -> tuple[ChangedPath, ...]:
        args = ["status", "--porcelain"]
        if untracked_all:
            args.append("--untracked-files=all")
        if paths:
            args.extend(["--", *paths])
        lines = [line for line in _git(self.repo, *args).splitlines() if line.strip()]
        return tuple(ChangedPath(path=line[3:].strip(), untracked=line.startswith("??")) for line in lines)

    def add(self, paths: Sequence[str]) -> None:
        _git(self.repo, "add", "--", *paths)

    def commit(self, message: str, trailers: Sequence[str] = ()) -> None:
        extra = [part for trailer in trailers for part in ("-m", trailer)]
        _git(self.repo, "commit", "-m", message, *extra)

    # -- the network -------------------------------------------------------------------------
    def fetch(self, auth: RealmSyncCredential | None) -> FetchOutcome:
        _git(self.repo, "fetch", extra_config=_credential_git_config(auth))
        return FetchOutcome.FETCHED

    def pull_fast_forward(self, auth: RealmSyncCredential | None) -> None:
        _git(self.repo, "pull", "--ff-only", extra_config=_credential_git_config(auth))

    def merge_remote_theirs(self, auth: RealmSyncCredential | None) -> MergeOutcome:
        extra = _credential_git_config(auth)
        proc = run_sync_git(("pull", "--no-rebase", "--no-edit", "-X", "theirs"), repo=self.repo,
                            config=(*_REPO_CONFIG, *(extra or ())))
        if proc.returncode == 0:
            return MergeOutcome()
        conflicts = tuple(line.strip() for line in _git(self.repo, "diff", "--name-only", "--diff-filter=U", check=False).splitlines() if line.strip())
        if conflicts:
            return MergeOutcome(conflicts=conflicts)
        raise _git_failure(["pull", "--no-rebase", "-X", "theirs"], proc, extra)

    def push(self, auth: RealmSyncCredential | None, *, set_upstream: bool) -> PushReport:
        args = ("push", "-u", "origin", "HEAD") if set_upstream else ("push",)
        extra = _credential_git_config(auth)
        proc = run_sync_git(args, repo=self.repo, config=(*_REPO_CONFIG, *(extra or ())))
        if proc.returncode == 0:
            return PushReport(PushOutcome.PUSHED)
        if _push_was_rejected(proc.stderr):
            return PushReport(PushOutcome.REJECTED, {
                "git_args": list(args), "stderr": _redact_text(_scrub_config_values(proc.stderr, extra))})
        raise _git_failure(list(args), proc, extra)

    # -- history -----------------------------------------------------------------------------
    def log(self, refs: Sequence[str], subtree: str, limit: int) -> list[LogEntry]:
        # --date-order: a child never sorts after its parent; two refs' commits made in one second tie on
        # the clock, and git's default walk then lists them in queue order.
        text = _git(self.repo, "log", "--date-order", f"-n{limit}", f"--format={_RECORD}%H{_FIELD}%aI{_FIELD}%an",
                    "--name-only", *refs, "--", subtree, check=False)
        entries: list[LogEntry] = []
        for record in text.split(_RECORD):
            lines = [line for line in record.splitlines() if line.strip()]
            if not lines:
                continue
            sha, at, author = (lines[0].split(_FIELD) + ["", ""])[:3]
            entries.append(LogEntry(sha=sha, at=at, author=author, paths=tuple(lines[1:])))
        return entries

    def newest(self, ref: str, subtree: str) -> str | None:
        return self._out("log", "-1", "--format=%H", ref, "--", subtree) or None
