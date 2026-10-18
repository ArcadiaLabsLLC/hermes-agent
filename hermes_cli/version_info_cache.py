"""Per-commit cache of the git answers ``hermes_cli.version_info`` derives its provenance from.

Fork-owned (lane q-version, owner ruling 2026-10-17, route 1). Every hermes process used to
spawn ~7 git processes for its version info (and the fleet updater's ``refresh=True`` 7 more);
on a large Windows clone that is 0.9-3.6 s per process start.

Mechanism, installed by two rebinding lines at the bottom of ``version_info``:

* ``memoize_run_git`` wraps ``_run_git``. ``rev-parse HEAD`` and ``branch --show-current`` are
  answered from the ``.git`` files (HEAD -> loose ref -> packed-refs; a worktree's ``.git`` file
  and ``commondir``), no process. Read-only queries whose answer is fixed by HEAD's commit and
  the tag refs (the tag list, a distance to a tag, the commit date, the short sha, a tag's
  pyproject) are answered from ``<git dir>/hermes-version-cache.json`` when its key matches,
  else run once and recorded. Anything else passes straight through. ``dirty`` is not a
  ``_run_git`` call and stays live.
* ``record_release`` wraps ``_git_version_info`` to record the derived ``base_version`` under
  the same key, which ``release_version`` reads for a User-Agent without spawning git.

The key is HEAD's commit plus the tag refs' state (packed-refs mtime/size and every loose
``refs/tags`` entry's name/mtime/size). The cache lives in the checkout's own git dir (a
worktree's private one): the answers are a property of that checkout, shared by every profile
and HERMES_HOME that runs it, and removed with it. Any read, parse or write failure falls back
to the git process the caller would have run anyway.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

CACHE_NAME = "hermes-version-cache.json"
_SCHEMA = 1
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


@dataclass(frozen=True)
class _Head:
    git_dir: Path
    common_dir: Path
    commit: str
    branch: str | None


def _git_dirs(repo_dir: Path) -> tuple[Path, Path] | None:
    dot_git = repo_dir / ".git"
    if dot_git.is_dir():
        git_dir = dot_git
    elif dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:"):
            return None
        git_dir = Path(text[len("gitdir:"):].strip())
        if not git_dir.is_absolute():
            git_dir = repo_dir / git_dir
    else:
        return None
    common_file = git_dir / "commondir"
    if common_file.is_file():
        common_dir = Path(common_file.read_text(encoding="utf-8").strip())
        if not common_dir.is_absolute():
            common_dir = git_dir / common_dir
    else:
        common_dir = git_dir
    return git_dir, common_dir


def _resolve_ref(git_dir: Path, common_dir: Path, ref: str) -> str | None:
    for base in (git_dir, common_dir):
        loose = base / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            return value if _SHA_RE.match(value) else None
    packed = common_dir / "packed-refs"
    if packed.is_file():
        with packed.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(("#", "^")):
                    continue
                sha, _, name = line.rstrip("\n").partition(" ")
                if name == ref:
                    return sha if _SHA_RE.match(sha) else None
    return None


def read_head(repo_dir: Path) -> _Head | None:
    """HEAD's commit and branch from the git files, or None for anything unusual."""
    try:
        dirs = _git_dirs(Path(repo_dir))
        if dirs is None:
            return None
        git_dir, common_dir = dirs
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head[len("ref:"):].strip()
            commit = _resolve_ref(git_dir, common_dir, ref)
            branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else None
        else:
            commit, branch = (head if _SHA_RE.match(head) else None), None
        return _Head(git_dir, common_dir, commit, branch) if commit else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _tags_state(common_dir: Path) -> str:
    digest = hashlib.sha1()
    packed = common_dir / "packed-refs"
    try:
        st = packed.stat()
        digest.update(f"packed {st.st_mtime_ns} {st.st_size}\n".encode())
    except FileNotFoundError:
        digest.update(b"packed -\n")
    tags_root = common_dir / "refs" / "tags"
    stack = [tags_root] if tags_root.is_dir() else []
    entries: list[str] = []
    while stack:
        with os.scandir(stack.pop()) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                else:
                    st = entry.stat(follow_symlinks=False)
                    entries.append(f"{entry.path} {st.st_mtime_ns} {st.st_size}")
    for line in sorted(entries):
        digest.update(line.encode("utf-8", "surrogateescape") + b"\n")
    return digest.hexdigest()


def _memoizable(args: tuple[str, ...]) -> bool:
    """A query whose answer only HEAD's commit and the tag refs decide."""
    if args == ("rev-parse", "--short=7", "HEAD") or args == ("log", "-1", "--format=%ct", "HEAD"):
        return True
    if args[:3] == ("tag", "--merged", "HEAD"):
        return True
    if len(args) == 3 and args[:2] == ("rev-list", "--count") and args[2].endswith("..HEAD"):
        return args[2][: -len("..HEAD")].startswith("v")
    if args[:1] == ("describe",) and args[-1] == "HEAD":
        return "--dirty" not in args and "--all" not in args
    if len(args) == 2 and args[0] == "show":
        ref, sep, _ = args[1].partition(":")
        return bool(sep) and ref.startswith("v")
    return False


class _Entry:
    def __init__(self, path: Path, commit: str, tags: str, answers: dict, fields: dict) -> None:
        self.path, self.commit, self.tags = path, commit, tags
        self.answers, self.fields = answers, fields

    def save(self) -> None:
        payload = {
            "schema": _SCHEMA, "commit": self.commit, "tags": self.tags,
            "answers": self.answers, "fields": self.fields,
        }
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass


_entries: dict[Path, _Entry] = {}


def _entry(head: _Head) -> _Entry:
    """The cache entry for HEAD's current key; a stale, missing or corrupt file starts empty."""
    tags = _tags_state(head.common_dir)
    path = head.git_dir / CACHE_NAME
    current = _entries.get(path)
    if current is not None and current.commit == head.commit and current.tags == tags:
        return current
    answers: dict = {}
    fields: dict = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(data, dict) and data.get("schema") == _SCHEMA
                and data.get("commit") == head.commit and data.get("tags") == tags
                and isinstance(data.get("answers"), dict) and isinstance(data.get("fields"), dict)
                and all(isinstance(v, str) for v in data["answers"].values())):
            answers, fields = data["answers"], data["fields"]
    except (OSError, ValueError):
        pass
    entry = _Entry(path, head.commit, tags, answers, fields)
    _entries[path] = entry
    return entry


def memoize_run_git(run_git: Callable[..., str | None]) -> Callable[..., str | None]:
    @functools.wraps(run_git)
    def cached_run_git(repo_dir: Path, *args: str) -> str | None:
        try:
            head = read_head(Path(repo_dir))
            if head is None:
                return run_git(repo_dir, *args)
            if args == ("rev-parse", "HEAD"):
                return head.commit
            if args == ("branch", "--show-current"):
                return head.branch
            if not _memoizable(args):
                return run_git(repo_dir, *args)
            entry = _entry(head)
        except (OSError, UnicodeDecodeError, ValueError):
            return run_git(repo_dir, *args)
        key = "\x1f".join(args)
        if key in entry.answers:
            return entry.answers[key]
        value = run_git(repo_dir, *args)
        if value is not None:  # None may be a timeout: never pin it for the commit's lifetime
            entry.answers[key] = value
            entry.save()
        return value

    cached_run_git.__wrapped_run_git__ = run_git  # type: ignore[attr-defined]
    return cached_run_git


def record_release(git_version_info: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(git_version_info)
    def recording_git_version_info(repo_dir: Path, *args: Any, **kwargs: Any) -> Any:
        info = git_version_info(repo_dir, *args, **kwargs)
        try:
            head = read_head(Path(repo_dir))
            if head is not None and head.commit == info.commit and info.base_version != "unknown":
                entry = _entry(head)
                if entry.fields.get("base_version") != info.base_version:
                    entry.fields["base_version"] = info.base_version
                    entry.save()
        except (OSError, UnicodeDecodeError, ValueError):
            pass
        return info

    return recording_git_version_info


def cached_base_version(repo_dir: Path) -> str | None:
    try:
        head = read_head(Path(repo_dir))
        if head is None:
            return None
        value = _entry(head).fields.get("base_version")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, str) and value else None


def release_version() -> str:
    """``base_version`` for a User-Agent; no git process once the commit is cached.

    The process's resolved identity, then the install stamp, then this checkout's per-commit
    cache; only on a miss of all three the full resolution, then the package metadata.
    """
    from hermes_cli import version_info

    if version_info._cached_version_info is not None:
        return version_info._cached_version_info.base_version
    try:
        stamped = version_info._stamp_version_info()
    except RuntimeError:
        stamped = None
    if stamped is not None:
        return stamped.base_version
    repo_dir = version_info._resolve_repo_dir()
    cached = cached_base_version(repo_dir) if repo_dir is not None else None
    if cached:
        return cached
    # First process on this commit: resolve once (which fills the cache for the next one). The
    # package metadata is a last resort only: a source checkout's pyproject says 0.0.0.
    resolved = version_info.get_version_info().base_version
    if resolved != "unknown":
        return resolved
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("hermes-agent")
    except PackageNotFoundError:
        return resolved


def _reset_for_tests() -> None:
    _entries.clear()
