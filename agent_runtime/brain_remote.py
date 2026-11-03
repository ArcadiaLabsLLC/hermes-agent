"""The brains' remote check: a fetch every few seconds, its upstream count in the brain-path list.

RT-BRAIN-PATHS-PLAIN-LIST slice 4 (owner sitting 2026-11-02, launcher plan
``EterniaLauncher/docs/mission_control/planned/THREE_BRAINS_ONE_READER_2026-11-02.md`` § Rulings, "Freshness"):

* every :data:`REMOTE_TICK_S` the serve's ticker (``hermes_cli/harness_parts/serve/queued_turns.py::
  start_brain_remote_ticker``) checks up to :data:`BRAINS_PER_TICK` brains of
  ``brain_paths.json`` (round robin, one checkout once however many slots bind it), one git process at a time;
* a brain whose branch has an upstream is fetched (bounded by :data:`FETCH_TIMEOUT_S`, never a prompt) and its
  ``HEAD..@{u}`` count measured;
* a WORKSPACE or PERSONAL brain (hermes's own repositories) that is behind and clean is fast-forwarded
  (``merge --ff-only``) and re-measured; a PROJECT brain is the user's working repo — only its count is kept,
  and it is never moved;
* the counts land in the list as each brain's ``behind`` (null: no upstream, not a repo, or unmeasured), so
  Eternia reads "N new upstream" without a call.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .brain_paths import brains, held_counts, read_brain_paths, write_brain_paths

__layer__ = "stores"
__all__ = ["BRAINS_PER_TICK", "FETCH_TIMEOUT_S", "REMOTE_TICK_S", "RemoteCheck", "check_brain"]

logger = logging.getLogger(__name__)

REMOTE_TICK_S = 5.0
#: A tick's bound: at most this many checkouts are fetched per tick; the rest wait for the next.
BRAINS_PER_TICK = 4
FETCH_TIMEOUT_S = 30
#: The brains hermes owns and may fast-forward; a ``project`` brain is the user's repo and only counted.
FAST_FORWARD_KINDS = frozenset({"personal", "workspace"})
_CONFIG = ("core.longpaths=true", "credential.interactive=never")
_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_ASKPASS": "", "SSH_ASKPASS": ""}


def _git(args: list[str], repo: Path, *, timeout: float = FETCH_TIMEOUT_S) -> subprocess.CompletedProcess[str] | None:
    from .git_cmd import run_git

    try:
        return run_git(args, repo=repo, config=_CONFIG, encoding="utf-8", errors="replace", timeout=timeout,
                       stdin=subprocess.DEVNULL, env={**os.environ, **_ENV})
    except (OSError, subprocess.TimeoutExpired):
        return None


def _count(repo: Path) -> int | None:
    done = _git(["rev-list", "--count", "HEAD..@{u}"], repo)
    if done is None or done.returncode != 0:
        return None
    try:
        return int(str(done.stdout).strip())
    except ValueError:
        return None


def _clean(repo: Path) -> bool:
    done = _git(["status", "--porcelain", "--untracked-files=no"], repo)
    return done is not None and done.returncode == 0 and not str(done.stdout).strip()


def check_brain(path: str, kind: str) -> int | None:
    """Fetch one brain's upstream and answer how far behind it is (after a fast-forward, for hermes's own)."""

    repo = Path(path)
    if not (repo / ".git").exists():
        return None
    upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], repo)
    if upstream is None or upstream.returncode != 0:
        return None
    _git(["fetch", "-q", "--no-tags"], repo)  # a failed fetch still counts against what is known
    behind = _count(repo)
    if kind in FAST_FORWARD_KINDS and behind and _clean(repo):
        merged = _git(["merge", "--ff-only", "-q", "@{u}"], repo)
        if merged is not None and merged.returncode == 0:
            behind = _count(repo)
    return behind


@dataclass
class RemoteCheck:
    """The ticker's state: a round-robin cursor and the counts measured so far, keyed by checkout path."""

    per_tick: int = BRAINS_PER_TICK
    cursor: int = 0
    counts: dict[str, int | None] = field(default_factory=dict)
    _inflight: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def due(self) -> list[tuple[str, str]]:
        """``(path, kind)`` of every checkout holding a brain, once each (the most-owned kind wins)."""

        seen: dict[str, str] = {}
        for kind, entry in brains(read_brain_paths()):
            path = entry.get("path")
            if isinstance(path, str) and path and entry.get("brain_dir"):
                # One checkout bound by a Project and hermes's own: never fast-forwarded (the user's wins).
                seen[path] = "project" if "project" in (kind, seen.get(path)) else kind
        return sorted(seen.items())

    def tick(self) -> dict[str, Any]:
        due = self.due()
        if not due:
            return {"checked": [], "written": False}
        start = self.cursor % len(due)
        batch = (due[start:] + due[:start])[: self.per_tick]
        self.cursor = start + len(batch)
        checked = []
        for path, kind in batch:
            with self._lock:
                if path in self._inflight:
                    continue
                self._inflight.add(path)
            try:
                self.counts[path] = check_brain(path, kind)
                checked.append(path)
            finally:
                with self._lock:
                    self._inflight.discard(path)
        here = dict(due)
        measured = {path: count for path, count in self.counts.items() if path in here}
        return {"checked": checked, "written": write_brain_paths(behind={**held_counts(), **measured})}

