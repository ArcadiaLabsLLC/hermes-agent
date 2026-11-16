"""The pure-Python git's answers to the realm-sync port (``git_port.SyncGit``), for a device with no git program.

A phone runs realm sync through ``dulwich`` (plan
``docs/agent-runtime-harness/planned/phone-realm-sync-dulwich-2026-11-16.md``, owner RULED dulwich).
This module NEVER starts a process (iOS ``subprocess`` raises ``ENOTSUP``): no ``porcelain``
network verb, no transport guessed from a URL, and commits are built from objects, so no hook
in ``.git/hooks`` can run. ``tests/agent_runtime/test_realm_sync_dulwich_spawns_nothing.py``
pins that negative over this file's source.

Where dulwich and git differ, this module answers as GIT does, because the shared contract
suite (``tests/agent_runtime/test_realm_sync_git_port.py``) holds both backends to one answer:
- ``remote_remove`` also deletes ``refs/remotes/<name>/*`` (``porcelain.remote_remove`` drops only
  the config section, and ``_follow_server_repository`` relies on stale tracking refs going);
- ``add`` stages the deletions under its paths, as ``git add <path>`` has since git 2.0
  (``porcelain.add`` stages none).
A failing step raises the same ``RealmSyncError`` codes the binary half raises.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from dulwich import porcelain
from dulwich.client import GitClient, HTTPUnauthorized, LocalGitClient, Urllib3HttpGitClient
from dulwich.config import ConfigDict
from dulwich.diff_tree import tree_changes
from dulwich.errors import GitProtocolError, HangupException, NotGitRepository
from dulwich.graph import can_fast_forward, find_merge_base
from dulwich.index import ConflictedIndexEntry, commit_tree, update_working_tree
from dulwich.object_store import tree_lookup_path
from dulwich.objects import Commit, Tree
from dulwich.objectspec import parse_commit
from dulwich.repo import Repo
from dulwich.walk import ORDER_DATE

from .git_port import ChangedPath, FetchOutcome, LogEntry, PushOutcome, PushReport, RepoState
from .models import RealmSyncError

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

__layer__ = "stores"
__all__ = ["DulwichSyncGit"]

_REMOTES = b"refs/remotes/"
_HEADS = b"refs/heads/"


def _b(text: str) -> bytes:
    return text.encode("utf-8")


def _s(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def _failure(git_args: Sequence[str], detail: str) -> RealmSyncError:
    """The refusal ``git._git_failure`` gives for a failed step, for a step dulwich could not take."""

    return RealmSyncError("sync_remote_unreachable", "git command failed for realm sync.", retryable=True,
                          safe_details={"git_args": list(git_args), "stderr": detail[-800:]})


class _BrokeredHttpClient(Urllib3HttpGitClient):
    """Smart HTTP with the credential Eternia brokers for this ONE call (Decision 4: never stored).

    The ``Authorization`` value (``Basic …`` or ``Bearer …``) rides dulwich's own per-origin slot, so a
    request to any other origin — a redirect included — carries none. Never ``extra_headers=`` (stored and
    never sent in 1.2.21) and never a config ``http.extraHeader`` (the pool sends it to every origin). An
    empty config: nothing of the member's own git config (helpers, headers, proxies' auth) is read."""

    def __init__(self, url: str, authorization: str | None) -> None:
        super().__init__(url, config=ConfigDict(), timeout=300)
        if authorization:
            self._auth_header = authorization
            self._auth_origin = self._origin(url)


class _Diverged(Exception):
    """The remote's branch is not an ancestor of ours: refused BEFORE anything is sent."""


def _identity() -> bytes:
    from .git import SYNC_IDENTITY

    pairs = dict(pair.split("=", 1) for pair in SYNC_IDENTITY)
    return _b(f"{pairs['user.name']} <{pairs['user.email']}>")


def _within_paths(path: str, prefixes: Sequence[str]) -> bool:
    if not prefixes:
        return True
    for prefix in prefixes:
        prefix = prefix.rstrip("/")
        if prefix in ("", ".") or path == prefix or path.startswith(prefix + "/"):
            return True
    return False


class DulwichSyncGit:
    """``git_port.SyncGit`` over dulwich, for the clone at ``repo``."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)

    def _open(self) -> Repo:
        try:
            return Repo(str(self.repo))
        except (NotGitRepository, FileNotFoundError, NotADirectoryError) as exc:
            raise _failure(["rev-parse", "--git-dir"], f"not a git repository: {self.repo.name}") from exc

    # -- the repository and its remotes ------------------------------------------------------
    def init(self) -> None:
        self.repo.mkdir(parents=True, exist_ok=True)
        Repo.init(str(self.repo)).close()

    def is_repo(self) -> bool:
        try:
            Repo(str(self.repo)).close()
        except (NotGitRepository, FileNotFoundError, NotADirectoryError):
            return False
        return True

    def remote_url(self, name: str) -> str | None:
        with self._open() as repo:
            try:
                return _s(repo.get_config().get((b"remote", _b(name)), b"url"))
            except KeyError:
                return None

    def remotes(self) -> tuple[str, ...]:
        with self._open() as repo:
            return tuple(_s(section[1]) for section in repo.get_config().sections()
                         if len(section) == 2 and section[0] == b"remote")

    def remote_add(self, name: str, url: str) -> None:
        with self._open() as repo:
            config = repo.get_config()
            if config.has_section((b"remote", _b(name))):
                raise _failure(["remote", "add", name, url], f"error: remote {name} already exists.")
            config.set((b"remote", _b(name)), b"url", _b(url))
            config.set((b"remote", _b(name)), b"fetch", _b(f"+refs/heads/*:refs/remotes/{name}/*"))
            config.write_to_path()

    def remote_remove(self, name: str, *, missing_ok: bool = False) -> None:
        with self._open() as repo:
            config = repo.get_config()
            section = (b"remote", _b(name))
            if not config.has_section(section):
                if missing_ok:
                    return
                raise _failure(["remote", "remove", name], f"error: No such remote: '{name}'")
            del config[section]
            # git also forgets every branch's upstream on that remote.
            for key in list(config.sections()):
                if len(key) == 2 and key[0] == b"branch" and _get(config, key, b"remote") == _b(name):
                    del config[key]
            config.write_to_path()
            # git drops the remote's tracking refs with it; dulwich does not.
            prefix = _REMOTES + _b(name) + b"/"
            for ref in [ref for ref in repo.refs.allkeys() if ref.startswith(prefix)]:
                repo.refs.remove_if_equals(ref, None)

    def has_remote_refs(self) -> bool:
        with self._open() as repo:
            return any(ref.startswith(_REMOTES) for ref in repo.refs.allkeys())

    # -- branches and refs -------------------------------------------------------------------
    def _head_ref(self, repo: Repo) -> bytes | None:
        names, _sha = repo.refs.follow(b"HEAD")
        target = names[-1] if names else None
        return target if target and target.startswith(_HEADS) else None

    def current_branch(self) -> str | None:
        with self._open() as repo:
            target = self._head_ref(repo)
            return _s(target[len(_HEADS):]) if target else None

    def rename_branch(self, branch: str) -> None:
        with self._open() as repo:
            new = _HEADS + _b(branch)
            old = self._head_ref(repo)
            sha = repo.refs[old] if old and old in repo.refs else None
            if sha is not None:
                repo.refs[new] = sha
            repo.refs.set_symbolic_ref(b"HEAD", new)
            if sha is not None and old is not None and old != new:
                repo.refs.remove_if_equals(old, None)

    def _resolve(self, repo: Repo, ref: str) -> bytes | None:
        try:
            return parse_commit(repo, _b(ref)).id
        except Exception:  # KeyError, ValueError, dulwich's AmbiguousShortId: "names no commit", as git says
            return None

    def resolve(self, ref: str) -> str | None:
        with self._open() as repo:
            sha = self._resolve(repo, ref)
            return _s(sha) if sha else None

    def _upstream(self, repo: Repo) -> tuple[bytes, str] | None:
        head = self._head_ref(repo)
        if head is None:
            return None
        config = repo.get_config()
        section = (b"branch", head[len(_HEADS):])
        try:
            remote, merge = config.get(section, b"remote"), config.get(section, b"merge")
        except KeyError:
            return None
        if not merge.startswith(_HEADS):
            return None
        ref = _REMOTES + remote + b"/" + merge[len(_HEADS):]
        if ref not in repo.refs:
            return None
        return ref, _s(remote + b"/" + merge[len(_HEADS):])

    def upstream(self) -> str | None:
        with self._open() as repo:
            found = self._upstream(repo)
            return found[1] if found else None

    def set_upstream(self, branch: str) -> None:
        with self._open() as repo:
            head = self._head_ref(repo)
            if head is None or _REMOTES + b"origin/" + _b(branch) not in repo.refs:
                raise _failure(["branch", f"--set-upstream-to=origin/{branch}"],
                               f"error: the requested upstream branch 'origin/{branch}' does not exist")
            config = repo.get_config()
            section = (b"branch", head[len(_HEADS):])
            config.set(section, b"remote", b"origin")
            config.set(section, b"merge", _HEADS + _b(branch))
            config.write_to_path()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        with self._open() as repo:
            a, d = self._resolve(repo, ancestor), self._resolve(repo, descendant)
            return bool(a and d) and (a == d or can_fast_forward(repo, a, d))

    def merge_base(self, a: str, b: str) -> str | None:
        with self._open() as repo:
            left, right = self._resolve(repo, a), self._resolve(repo, b)
            if not (left and right):
                return None
            bases = find_merge_base(repo, [left, right])
            return _s(bases[0]) if bases else None

    def tree_paths(self, ref: str) -> frozenset[str]:
        with self._open() as repo:
            sha = self._resolve(repo, ref)
            if sha is None:
                return frozenset()
            tree = repo[sha].tree
            return frozenset(_s(entry.path) for entry in repo.object_store.iter_tree_contents(tree))

    def read_tree_at(self, sha: str, rel: str, dest: Path) -> Path | None:
        with self._open() as repo:
            commit = self._resolve(repo, sha)
            if commit is None:
                raise _failure(["archive", sha, rel], f"fatal: not a valid object name: {sha}")
            try:
                _mode, sub = tree_lookup_path(repo.object_store.__getitem__, repo[commit].tree, _b(rel))
            except KeyError:
                return None
            root = dest / "tree"
            target = root.joinpath(*rel.split("/"))
            if not isinstance(repo[sub], Tree):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(repo[sub].as_raw_string())
                return target
            for entry in repo.object_store.iter_tree_contents(sub):
                out = target.joinpath(*_s(entry.path).split("/"))
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(repo[entry.sha].as_raw_string())
            target.mkdir(parents=True, exist_ok=True)
            return target

    # -- the working tree and the index ------------------------------------------------------
    def is_tracked(self, path: str) -> bool:
        with self._open() as repo:
            return _b(path) in repo.open_index()

    def _conflicts(self, repo: Repo) -> tuple[str, ...]:
        index = repo.open_index()
        return tuple(sorted(_s(path) for path, entry in index.items() if isinstance(entry, ConflictedIndexEntry)))

    def state(self) -> RepoState:
        with self._open() as repo:
            conflicts = self._conflicts(repo)
            head = self._resolve(repo, "HEAD")
            ahead = behind = 0
            upstream = self._upstream(repo)
            if upstream is not None and head is not None:
                theirs = repo.refs[upstream[0]]
                ahead = sum(1 for _ in repo.get_walker(include=[head], exclude=[theirs]))
                behind = sum(1 for _ in repo.get_walker(include=[theirs], exclude=[head]))
            elif head is not None and self._remote_tips(repo) is not None:
                tips = self._remote_tips(repo) or []
                ahead = sum(1 for _ in repo.get_walker(include=[head], exclude=tips))
        return RepoState(ahead=ahead, behind=behind, conflicts=conflicts, dirty=bool(self.changed()))

    def _remote_tips(self, repo: Repo) -> list[bytes] | None:
        """Every remote-tracking tip, or ``None`` when the repository names no remote at all."""

        if not any(len(s) == 2 and s[0] == b"remote" for s in repo.get_config().sections()):
            return None
        return [repo.refs[ref] for ref in repo.refs.allkeys() if ref.startswith(_REMOTES) and not ref.endswith(b"/HEAD")]

    def changed(self, paths: Sequence[str] = (), *, untracked_all: bool = False) -> tuple[ChangedPath, ...]:
        with self._open() as repo:
            status = porcelain.status(repo, untracked_files="all" if untracked_all else "normal")
            tracked = {_s(p) for group in status.staged.values() for p in group}
            tracked |= {_s(p) for p in status.unstaged}
            tracked |= set(self._conflicts(repo))
            untracked = {_s(p) for p in status.untracked}
        rows = [ChangedPath(path=p, untracked=False) for p in tracked if _within_paths(p, paths)]
        rows += [ChangedPath(path=p, untracked=True) for p in untracked - tracked if _within_paths(p, paths)]
        return tuple(sorted(rows, key=lambda row: row.path))

    def add(self, paths: Sequence[str], *, all_under: bool = False) -> None:
        # ``all_under`` is git's ``add -A``; since git 2.0 ``add <path>`` stages the deletions under it too,
        # so both stage them here.
        with self._open() as repo:
            present = [str(self.repo / p) for p in paths if (self.repo / p).exists()]
            missing = [p for p in paths if not (self.repo / p).exists()]
            index = repo.open_index()
            if missing and not any(_within_paths(_s(key), missing) for key in index):
                raise _failure(["add", "--", *paths], f"fatal: pathspec '{missing[0]}' did not match any files")
            if present:
                porcelain.add(repo, present)
            index = repo.open_index()
            gone = [key for key in index if _within_paths(_s(key), paths) and not (self.repo / _s(key)).exists()]
            for key in gone:
                del index[key]
            if gone:
                index.write()

    def move(self, old: str, new: str) -> None:
        with self._open() as repo:
            source, target = self.repo / old, self.repo / new
            if not source.exists() or target.exists():
                raise _failure(["mv", old, new], f"fatal: bad source, source={old}, destination={new}")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            index = repo.open_index()
            prefix = old.rstrip("/")
            for key in [key for key in index if _within_paths(_s(key), [prefix])]:
                entry = index[key]
                del index[key]
                index[_b(new.rstrip("/") + _s(key)[len(prefix):])] = entry
            index.write()

    def commit(self, message: str, trailers: Sequence[str] = (), *, paths: Sequence[str] = ()) -> None:
        with self._open() as repo:
            index = repo.open_index()
            if index.has_conflicts():
                raise _failure(["commit"], "error: Committing is not possible because you have unmerged files.")
            head = self._resolve(repo, "HEAD")
            staged = {key: (entry.sha, entry.mode) for key, entry in index.items()}
            if paths and head is not None:
                kept = {entry.path: (entry.sha, entry.mode)
                        for entry in repo.object_store.iter_tree_contents(repo[head].tree)
                        if not _within_paths(_s(entry.path), paths)}
                staged = {**kept, **{key: value for key, value in staged.items() if _within_paths(_s(key), paths)}}
            tree = commit_tree(repo.object_store, [(key, sha, mode) for key, (sha, mode) in staged.items()])
            if head is not None and repo[head].tree == tree:
                raise _failure(["commit", "-m", message], "nothing to commit, working tree clean")
            self._write_commit(repo, tree, [head] if head is not None else [],
                               "\n\n".join([message, *trailers]) + "\n")

    def _write_commit(self, repo: Repo, tree: bytes, parents: list[bytes], message: str) -> bytes:
        commit = Commit()
        commit.tree = tree
        commit.parents = parents
        commit.author = commit.committer = _identity()
        now = int(time.time())
        offset = -(time.altzone if time.daylight and time.localtime(now).tm_isdst > 0 else time.timezone)
        commit.author_time = commit.commit_time = now
        commit.author_timezone = commit.commit_timezone = offset
        commit.encoding = b"UTF-8"
        commit.message = _b(message)
        repo.object_store.add_object(commit)
        target = self._head_ref(repo)
        if target is None:  # a detached HEAD moves itself
            repo.refs[b"HEAD"] = commit.id
        elif not repo.refs.set_if_equals(target, parents[0] if parents else None, commit.id):
            raise _failure(["commit"], "fatal: cannot lock ref: the branch moved during the commit")
        return commit.id

    def reset_hard(self, ref: str) -> None:
        with self._open() as repo:
            sha = self._resolve(repo, ref)
            if sha is None:
                raise _failure(["reset", "-q", "--hard", ref], f"fatal: ambiguous argument '{ref}'")
            target = self._head_ref(repo)
            if target is not None:
                repo.refs[target] = sha
            else:
                repo.refs[b"HEAD"] = sha
            porcelain.reset(repo, "hard", sha)

    # -- the network -------------------------------------------------------------------------
    def _transport(self, url: str, step: Sequence[str]) -> tuple[GitClient, str]:
        """The client for ``url``, built here and never guessed from it (no process, no ssh)."""

        if url.startswith(("http://", "https://")):
            return _BrokeredHttpClient(url, None), urlparse(url).path
        if url.startswith("file://"):
            return LocalGitClient(), unquote(urlparse(url).path)
        if "://" in url or url.startswith("git@") or (":" in url.split("/", 1)[0] and len(url.split(":", 1)[0]) > 1):
            raise RealmSyncError(
                "sync_remote_unreachable",
                "This device syncs realms over https only; this realm's remote is not reachable from it.",
                retryable=False,
                safe_details={"git_args": list(step), "reason": "transport_not_on_this_device"},
            )
        return LocalGitClient(), url

    def _client(self, url: str, auth: RealmSyncCredential | None, step: Sequence[str]) -> tuple[GitClient, str]:
        client, path = self._transport(url, step)
        if isinstance(client, Urllib3HttpGitClient) and auth is not None:
            client = _BrokeredHttpClient(url, auth.git_authorization)
        return client, path

    def _wire(self, step: Sequence[str], url: str, auth: RealmSyncCredential | None, call: Callable[[], Any]) -> Any:
        """Run one network exchange; any failure is the typed refusal git's would be, scrubbed of the credential."""

        try:
            return call()
        except (RealmSyncError, _Diverged):
            raise
        except HTTPUnauthorized as exc:
            detail = f"fatal: Authentication failed for '{url}'"
            cause: Exception = exc
        except NotGitRepository as exc:
            detail = (f"remote: Repository not found.\nfatal: unable to access '{url}': The requested URL returned error: 404"
                      if url.startswith("http") else f"fatal: '{url}' does not appear to be a git repository")
            cause = exc
        except GitProtocolError as exc:
            status = str(exc).split("unexpected http resp ", 1)
            detail = (f"fatal: unable to access '{url}': The requested URL returned error: {status[1].split()[0]}"
                      if len(status) == 2 else f"fatal: {exc}")
            cause = exc
        except (HangupException, OSError, KeyError, ValueError) as exc:
            detail = f"fatal: unable to access '{url}': {exc}"
            cause = exc
        from .git import _redact_text, _scrub_config_values

        secrets = auth.git_extra_config() + [f"x={auth.git_authorization}"] if auth is not None else []
        text = _redact_text(_scrub_config_values(detail, secrets))
        code = "sync_auth_failed" if "authentication" in text.lower() else "sync_remote_unreachable"
        raise RealmSyncError(code, "git command failed for realm sync.", retryable=True,
                             safe_details={"git_args": list(step), "stderr": text}) from cause

    def _fetch(self, repo: Repo, auth: RealmSyncCredential | None, step: Sequence[str],
               branch: str | None = None) -> tuple[dict[bytes, bytes], dict[bytes, bytes]]:
        """Fetch ``origin``'s branches (or one) into ``refs/remotes/origin/*``; the remote's heads and symrefs."""

        url = _get(repo.get_config(), (b"remote", b"origin"), b"url")
        if url is None:
            raise _failure(step, "fatal: 'origin' does not appear to be a git repository")
        location = _s(url)
        client, path = self._client(location, auth, step)
        only = _HEADS + _b(branch) if branch is not None else None

        def wants(refs: dict[bytes, bytes], *_args: Any, **_kwargs: Any) -> list[bytes]:
            return sorted({sha for ref, sha in refs.items() if sha and ref.startswith(_HEADS)
                           and (only is None or ref == only) and sha not in repo.object_store})

        result = self._wire(step, location, auth, lambda: client.fetch(path, repo, determine_wants=wants))
        heads = {ref: sha for ref, sha in (result.refs or {}).items()
                 if sha and ref.startswith(_HEADS) and (only is None or ref == only)}
        for ref, sha in heads.items():
            repo.refs[_REMOTES + b"origin/" + ref[len(_HEADS):]] = sha
        return heads, dict(result.symrefs or {})

    def fetch(self, auth: RealmSyncCredential | None, *, branch: str | None = None) -> FetchOutcome:
        step = ["fetch"] if branch is None else ["fetch", "-q", "origin", branch]
        with self._open() as repo:
            heads, _symrefs = self._fetch(repo, auth, step, branch)
        return FetchOutcome.EMPTY_REMOTE if branch is not None and not heads else FetchOutcome.FETCHED

    def clone(self, url: str, auth: RealmSyncCredential | None) -> None:
        made = not self.repo.exists()
        try:
            self.init()
            with self._open() as repo:
                config = repo.get_config()
                config.set((b"remote", b"origin"), b"url", _b(url))
                config.set((b"remote", b"origin"), b"fetch", b"+refs/heads/*:refs/remotes/origin/*")
                config.write_to_path()
                heads, symrefs = self._fetch(repo, auth, ["clone", url], None)
                head = symrefs.get(b"HEAD")
                if head not in heads:
                    head = next((ref for ref in (_HEADS + b"main", _HEADS + b"master") if ref in heads),
                                min(heads) if heads else head)
                if head:
                    repo.refs.set_symbolic_ref(b"HEAD", head)
                if head in heads:
                    repo.refs[head] = heads[head]
                    section = (b"branch", head[len(_HEADS):])
                    config.set(section, b"remote", b"origin")
                    config.set(section, b"merge", head)
                    config.write_to_path()
                    porcelain.reset(repo, "hard", heads[head])
        except RealmSyncError as exc:
            if made:
                shutil.rmtree(self.repo, ignore_errors=True)
            raise RealmSyncError(exc.code, "Could not clone realm sync repository.", retryable=exc.retryable,
                                 safe_details={key: value for key, value in exc.safe_details.items() if key != "git_args"}) from exc

    def pull_fast_forward(self, auth: RealmSyncCredential | None) -> None:
        step = ["pull", "--ff-only"]
        with self._open() as repo:
            self._fetch(repo, auth, step)
            upstream = self._upstream(repo)
            if upstream is None:
                raise _failure(step, "There is no tracking information for the current branch.")
            theirs, head, branch = repo.refs[upstream[0]], self._resolve(repo, "HEAD"), self._head_ref(repo)
            if head == theirs or (head is not None and can_fast_forward(repo, theirs, head)):
                return  # already up to date
            if head is not None and not can_fast_forward(repo, head, theirs):
                raise _failure(step, "fatal: Not possible to fast-forward, aborting.")
            self._move_to(repo, head, theirs, branch, step)

    def _move_to(self, repo: Repo, head: bytes | None, theirs: bytes, branch: bytes | None, step: Sequence[str]) -> None:
        """Check ``theirs`` out over ``head`` (never over a modified file) and move the branch to it."""

        old_tree = repo[head].tree if head is not None else None
        new_tree = repo[theirs].tree
        try:
            update_working_tree(repo, old_tree, new_tree,
                                change_iterator=tree_changes(repo.object_store, old_tree, new_tree),
                                allow_overwrite_modified=False)
        except (OSError, ValueError) as exc:
            raise _failure(step, f"error: Your local changes would be overwritten: {exc}") from exc
        if branch is None:
            repo.refs[b"HEAD"] = theirs
        elif not repo.refs.set_if_equals(branch, head, theirs):
            raise _failure(step, "fatal: cannot lock ref: the branch moved during the pull")

    def push(self, auth: RealmSyncCredential | None, *, set_upstream: bool, branch: str | None = None) -> PushReport:
        if branch is not None:
            step = ["push", "-q", "-u", "origin", f"HEAD:{branch}"]
        else:
            step = ["push", "-u", "origin", "HEAD"] if set_upstream else ["push"]
        with self._open() as repo:
            head_ref = self._head_ref(repo)
            local = repo.refs[head_ref] if head_ref is not None and head_ref in repo.refs else None
            if local is None:
                raise _failure(step, "error: src refspec HEAD does not match any")
            config = repo.get_config()
            merge = _get(config, (b"branch", head_ref[len(_HEADS):]), b"merge")
            if branch is not None:
                target = _HEADS + _b(branch)
            elif set_upstream:
                target = head_ref
            elif merge is not None:
                target = merge
            else:
                raise _failure(step, f"fatal: The current branch {_s(head_ref[len(_HEADS):])} has no upstream branch.")
            url = _get(config, (b"remote", b"origin"), b"url")
            if url is None:
                raise _failure(step, "fatal: 'origin' does not appear to be a git repository")
            location = _s(url)
            client, path = self._client(location, auth, step)

            def update_refs(refs: dict[bytes, bytes]) -> dict[bytes, bytes]:
                # dulwich's send_pack replaces a diverged remote branch (a teammate's newer publish);
                # git refuses it client-side. So do we, before a byte is sent.
                old = refs.get(target)
                if old and old != local and not (old in repo.object_store and can_fast_forward(repo, old, local)):
                    raise _Diverged(_s(old))
                return {target: local}

            def pack(have: Any, want: Any, *, ofs_delta: bool = False, progress: Any = None) -> Any:
                return repo.generate_pack_data(set(have), set(want), progress=progress, ofs_delta=ofs_delta)

            try:
                result = self._wire(step, location, auth, lambda: client.send_pack(_b(path), update_refs, pack))
            except _Diverged:
                return PushReport(PushOutcome.REJECTED, {
                    "git_args": step,
                    "stderr": f" ! [rejected]        HEAD -> {_s(target[len(_HEADS):])} (fetch first)"})
            refused = (getattr(result, "ref_status", None) or {}).get(target)
            if refused:
                text = f" ! [remote rejected] HEAD -> {_s(target[len(_HEADS):])} ({refused})"
                if any(tell in refused for tell in ("non-fast-forward", "fetch first", "stale info")):
                    return PushReport(PushOutcome.REJECTED, {"git_args": step, "stderr": text})
                raise _failure(step, text)
            repo.refs[_REMOTES + b"origin/" + target[len(_HEADS):]] = local
            if set_upstream or branch is not None:
                section = (b"branch", head_ref[len(_HEADS):])
                config.set(section, b"remote", b"origin")
                config.set(section, b"merge", target)
                config.write_to_path()
        return PushReport(PushOutcome.PUSHED)

    # -- history -----------------------------------------------------------------------------
    def log(self, refs: Sequence[str], subtree: str, limit: int) -> list[LogEntry]:
        with self._open() as repo:
            include = [sha for sha in (self._resolve(repo, ref) for ref in refs) if sha is not None]
            if not include:
                return []
            prefix = subtree.rstrip("/")
            entries: list[LogEntry] = []
            for walk in repo.get_walker(include=include, paths=[_b(prefix)], order=ORDER_DATE, max_entries=limit):
                commit = walk.commit
                touched: list[str] = []
                if len(commit.parents) <= 1:  # git's --name-only names no file of a merge
                    for change in walk.changes():
                        for side in (change.new, change.old):
                            if side is not None and side.path is not None:
                                touched.append(_s(side.path))
                                break
                paths = tuple(dict.fromkeys(p for p in sorted(touched) if _within_paths(p, [prefix])))
                entries.append(LogEntry(sha=_s(commit.id), at=_iso(commit.author_time, commit.author_timezone),
                                        author=_s(commit.author).split(" <", 1)[0], paths=paths))
            return entries

    def newest(self, ref: str, subtree: str) -> str | None:
        found = self.log([ref], subtree, 1)
        return found[0].sha if found else None


def _get(config, section: tuple[bytes, ...], name: bytes) -> bytes | None:
    try:
        return config.get(section, name)
    except KeyError:
        return None


def _iso(stamp: int, offset: int) -> str:
    return datetime.fromtimestamp(stamp, timezone(timedelta(seconds=offset))).isoformat()

