"""The git program's answers to the realm-sync port (``git_port.SyncGit``): today's argv, behind the verbs.

Each verb runs exactly the argv its call site ran before the port and parses git's text
HERE, so no caller reads git's output again. A failing step raises the ``RealmSyncError``
``git._git`` always raised (``git._git_failure``: the same ``git_args`` and scrubbed
``stderr``).

``BinarySyncGit(repo)`` is realm sync's: every step through ``git.run_sync_git`` with
``git._REPO_CONFIG`` (the ``SYNC_IDENTITY`` pair, ``core.longpaths``, the identity variables
dropped, prompts off), the credential per network step. ``git_remote_adopt.adopt_remote``'s
``run=`` / ``config=`` build the same class over the caller's runner and ``-c`` pairs (the
default brain's adoption keeps ``git_cmd.run_git``), so the adopter has ONE door, the port.
"""

from __future__ import annotations

import subprocess
import tarfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import git as _sync
from .git import _credential_git_config, _git_clone, _git_failure, _push_was_rejected, _redact_text, _scrub_config_values
from .git_port import ChangedPath, FetchOutcome, LogEntry, MergeOutcome, PushOutcome, PushReport, RepoState

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

__layer__ = "stores"
__all__ = ["BinarySyncGit"]

#: Separators ``git log --format`` writes between records and fields (ASCII RS / US),
#: which no sha, date or author name carries.
_RECORD, _FIELD = "\x1e", "\x1f"
#: What ``git fetch origin <branch>`` says when the remote has no such branch (an empty repository).
_EMPTY_REMOTE = "couldn't find remote ref"


class BinarySyncGit:
    """``git_port.SyncGit`` over the host's git program, for the clone at ``repo``.

    ``run`` / ``config`` / ``run_kwargs`` default to realm sync's door; ``config`` given by a
    caller is also what every refusal scrubs (it may carry a credential header)."""

    def __init__(self, repo: Path, *, run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
                 config: Sequence[str] | None = None, run_kwargs: Mapping[str, Any] | None = None) -> None:
        self.repo = Path(repo)
        self._run = run
        self._config = tuple(str(pair) for pair in config) if config is not None else None
        self._run_kwargs = dict(run_kwargs or {})

    # -- the one runner ----------------------------------------------------------------------
    def _proc(self, args: Sequence[str], extra: Sequence[str] | None = None) -> subprocess.CompletedProcess[str]:
        run = self._run or _sync.run_sync_git
        config = self._config if self._config is not None else _sync._REPO_CONFIG
        return run(list(args), repo=self.repo, config=(*config, *(extra or ())), **self._run_kwargs)

    def _secret(self, extra: Sequence[str] | None) -> tuple[str, ...]:
        return (*(self._config or ()), *(extra or ()))

    def _step(self, *args: str, check: bool = True, extra: Sequence[str] | None = None) -> str:
        proc = self._proc(args, extra)
        if check and proc.returncode != 0:
            raise _git_failure(list(args), proc, self._secret(extra))
        return str(proc.stdout or "")

    def _out(self, *args: str) -> str:
        return self._step(*args, check=False).strip()

    def _ok(self, *args: str) -> bool:
        return self._proc(args).returncode == 0

    # -- the repository and its remotes ------------------------------------------------------
    def init(self) -> None:
        self._step("init")

    def is_repo(self) -> bool:
        return self._ok("rev-parse", "--git-dir")

    def clone(self, url: str, auth: RealmSyncCredential | None) -> None:
        _git_clone(url, self.repo, extra_config=_credential_git_config(auth))

    def remote_url(self, name: str) -> str | None:
        # raw: ``remote get-url`` would apply ``insteadOf``.
        return self._out("config", "--get", f"remote.{name}.url") or None

    def remotes(self) -> tuple[str, ...]:
        return tuple(self._step("remote", check=False).split())

    def remote_add(self, name: str, url: str) -> None:
        self._step("remote", "add", name, url)

    def remote_remove(self, name: str, *, missing_ok: bool = False) -> None:
        # git drops the remote's tracking refs with it.
        self._step("remote", "remove", name, check=not missing_ok)

    def has_remote_refs(self) -> bool:
        return bool(self._out("for-each-ref", "--count=1", "refs/remotes"))

    # -- branches and refs -------------------------------------------------------------------
    def current_branch(self) -> str | None:
        return self._out("symbolic-ref", "--short", "-q", "HEAD") or None

    def rename_branch(self, branch: str) -> None:
        if self.resolve("HEAD"):
            self._step("branch", "-M", branch)
        else:
            self._step("symbolic-ref", "HEAD", f"refs/heads/{branch}")

    def resolve(self, ref: str) -> str | None:
        return self._out("rev-parse", "-q", "--verify", f"{ref}^{{commit}}") or None

    def upstream(self) -> str | None:
        return self._out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") or None

    def set_upstream(self, branch: str) -> None:
        self._step("branch", f"--set-upstream-to=origin/{branch}")

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self._ok("merge-base", "--is-ancestor", ancestor, descendant)

    def merge_base(self, a: str, b: str) -> str | None:
        return self._out("merge-base", a, b) or None

    def tree_paths(self, ref: str) -> frozenset[str]:
        return frozenset(line for line in self._out("ls-tree", "-r", "--name-only", ref).splitlines() if line)

    def read_tree_at(self, sha: str, rel: str, dest: Path) -> Path | None:
        if not self._ok("cat-file", "-e", f"{sha}:{rel}"):
            return None
        archive = dest / "version.tar"
        self._step("archive", "--format=tar", "-o", str(archive), sha, rel)
        tree = dest / "tree"
        with tarfile.open(archive) as tar:
            tar.extractall(tree, filter="data")
        return tree.joinpath(*rel.split("/"))

    # -- the working tree and the index ------------------------------------------------------
    def is_tracked(self, path: str) -> bool:
        return bool(self._out("ls-files", "--", path))

    def state(self) -> RepoState:
        conflicts = tuple(line.strip() for line in self._step("diff", "--name-only", "--diff-filter=U", check=False).splitlines() if line.strip())
        ahead = behind = 0
        if self.upstream():
            counts = self._step("rev-list", "--left-right", "--count", "HEAD...@{u}", check=False).split()
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
        lines = [line for line in self._step(*args).splitlines() if line.strip()]
        return tuple(ChangedPath(path=line[3:].strip(), untracked=line.startswith("??")) for line in lines)

    def add(self, paths: Sequence[str], *, all_under: bool = False) -> None:
        self._step("add", *(("-A",) if all_under else ()), "--", *paths)

    def move(self, old: str, new: str) -> None:
        self._step("mv", old, new)

    def commit(self, message: str, trailers: Sequence[str] = (), *, paths: Sequence[str] = ()) -> None:
        extra = [part for trailer in trailers for part in ("-m", trailer)]
        self._step("commit", "-m", message, *extra, *(("--", *paths) if paths else ()))

    def reset_hard(self, ref: str) -> None:
        self._step("reset", "-q", "--hard", ref)

    # -- the network -------------------------------------------------------------------------
    def fetch(self, auth: RealmSyncCredential | None, *, branch: str | None = None) -> FetchOutcome:
        extra = _credential_git_config(auth)
        if branch is None:
            self._step("fetch", extra=extra)
            return FetchOutcome.FETCHED
        args = ("fetch", "-q", "origin", branch)
        proc = self._proc(args, extra)
        if proc.returncode == 0:
            return FetchOutcome.FETCHED
        if _EMPTY_REMOTE in str(proc.stderr or ""):
            return FetchOutcome.EMPTY_REMOTE
        raise _git_failure(list(args), proc, self._secret(extra))

    def pull_fast_forward(self, auth: RealmSyncCredential | None) -> None:
        self._step("pull", "--ff-only", extra=_credential_git_config(auth))

    def merge_remote_theirs(self, auth: RealmSyncCredential | None) -> MergeOutcome:
        extra = _credential_git_config(auth)
        proc = self._proc(("pull", "--no-rebase", "--no-edit", "-X", "theirs"), extra)
        if proc.returncode == 0:
            return MergeOutcome()
        conflicts = tuple(line.strip() for line in self._step("diff", "--name-only", "--diff-filter=U", check=False).splitlines() if line.strip())
        if conflicts:
            return MergeOutcome(conflicts=conflicts)
        raise _git_failure(["pull", "--no-rebase", "-X", "theirs"], proc, self._secret(extra))

    def merge_unrelated_ours(self, tip: str) -> None:
        self._step("merge", "-q", "--allow-unrelated-histories", "--no-edit", "-X", "ours", tip)

    def push(self, auth: RealmSyncCredential | None, *, set_upstream: bool, branch: str | None = None) -> PushReport:
        if branch is not None:
            args: tuple[str, ...] = ("push", "-q", "-u", "origin", f"HEAD:{branch}")
        else:
            args = ("push", "-u", "origin", "HEAD") if set_upstream else ("push",)
        extra = _credential_git_config(auth)
        proc = self._proc(args, extra)
        if proc.returncode == 0:
            return PushReport(PushOutcome.PUSHED)
        if _push_was_rejected(str(proc.stderr or "")):
            return PushReport(PushOutcome.REJECTED, {
                "git_args": list(args),
                "stderr": _redact_text(_scrub_config_values(str(proc.stderr or ""), self._secret(extra)))})
        raise _git_failure(list(args), proc, self._secret(extra))

    # -- history -----------------------------------------------------------------------------
    def log(self, refs: Sequence[str], subtree: str, limit: int) -> list[LogEntry]:
        # --date-order: a child never sorts after its parent; two refs' commits made in one second tie on
        # the clock, and git's default walk then lists them in queue order.
        text = self._step("log", "--date-order", f"-n{limit}", f"--format={_RECORD}%H{_FIELD}%aI{_FIELD}%an",
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
