"""The one door that gives an existing git repository its ``origin`` (p10-work plan §2.3, stage R0).

``adopt_remote(repo, url)`` is shared by the default brain's promotion (a brain repo hermes just
created on the git host: the remote is empty, or the local directory is) and the local realm's
personal repo (``REALM-LOCAL-REMOTE-FROM-CREDENTIAL``: two machines of one player may each hold
commits). Every step is one ``git_cmd.run_git`` call with ``config`` rendered as ``-c`` pairs, so a
credential (``http.extraHeader=Authorization: …``) never touches ``.git/config``; stderr is scrubbed
with ``realm_sync.git._scrub_config_values`` before it reaches a refusal.

The step table, after ``remote get-url origin`` (equal → kept; different → ``url_mismatch``; absent
→ ``remote add``) and ``fetch origin <branch>`` (a missing branch is an EMPTY remote):

| local has commits | remote has commits | outcome |
|---|---|---|
| no | yes | ``reset --hard origin/<branch>`` + upstream → ``ADDED_FETCHED`` |
| yes | no | ``push -u origin HEAD:<branch>`` → ``ADDED_PUSHED`` |
| yes | yes, shared history | upstream set if unset → ``ALREADY`` |
| yes | yes, unrelated | disjoint paths (``.gitattributes`` aside) and the caller allows it → ``merge --allow-unrelated-histories -X ours`` → ``MERGED_UNRELATED``; else ``remote_diverged`` |
| no | no | nothing to move → ``ALREADY`` (``detail="empty"``) |

Receipt: ``git.remote_adopted {repo (basename), outcome, branch}`` through ``work_store.receipts.emit``.
Pinned by ``tests/agent_runtime/test_git_remote_adopt.py``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .git_cmd import run_git

__layer__ = "stores"
__all__ = ["AdoptReceipt", "AdoptRefused", "Adoption", "adopt_remote"]

#: The one path two subtrees may both carry (the realm repo's managed file; ours wins).
SHARED_OK = frozenset({".gitattributes"})
_EMPTY_REMOTE = "couldn't find remote ref"


class Adoption(StrEnum):
    ADDED_PUSHED = "added_pushed"
    ADDED_FETCHED = "added_fetched"
    ALREADY = "already"
    MERGED_UNRELATED = "merged_unrelated"


@dataclass(frozen=True)
class AdoptReceipt:
    outcome: Adoption
    url: str
    branch: str
    head: str
    detail: str = ""


class AdoptRefused(ValueError):
    """``reason``: ``url_mismatch`` | ``remote_diverged`` | ``fetch_failed`` | ``push_failed`` | ``not_a_repo``."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass
class _Door:
    repo: Path
    config: tuple[str, ...]
    run: Callable[..., subprocess.CompletedProcess[str]]

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run(list(args), repo=self.repo, config=self.config, encoding="utf-8", errors="replace",
                        timeout=300, stdin=subprocess.DEVNULL)

    def ok(self, *args: str) -> bool:
        return self.git(*args).returncode == 0

    def out(self, *args: str) -> str:
        done = self.git(*args)
        return str(done.stdout or "").strip() if done.returncode == 0 else ""

    def scrub(self, text: str) -> str:
        from .realm_sync.git import _scrub_config_values

        return _scrub_config_values(str(text or ""), self.config).strip()[-400:]

    def must(self, reason: str, *args: str) -> str:
        done = self.git(*args)
        if done.returncode != 0:
            raise AdoptRefused(reason, f"git {args[0]}: {self.scrub(done.stderr)}")
        return str(done.stdout or "").strip()

    def ensure_upstream(self, branch: str) -> None:
        if not self.ok("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
            self.git("branch", f"--set-upstream-to=origin/{branch}")


def _paths(door: _Door, ref: str) -> set[str]:
    return set(door.out("ls-tree", "-r", "--name-only", ref).splitlines())


def adopt_remote(
    repo: Path,
    url: str,
    *,
    branch: str = "main",
    config: Sequence[str] = (),
    merge_unrelated_if_disjoint: bool = False,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_git,
) -> AdoptReceipt:
    """Make ``url`` the ``origin`` of ``repo`` and reconcile the two histories (module docstring's table)."""

    door = _Door(Path(repo), tuple(str(pair) for pair in config), run)
    if not door.ok("rev-parse", "--git-dir"):
        raise AdoptRefused("not_a_repo", str(Path(repo).name))
    current = door.git("remote", "get-url", "origin")
    if current.returncode == 0:
        if str(current.stdout or "").strip() != url:
            raise AdoptRefused("url_mismatch", "origin names another remote")
    else:
        door.must("not_a_repo", "remote", "add", "origin", url)
    fetched = door.git("fetch", "-q", "origin", branch)
    if fetched.returncode != 0 and _EMPTY_REMOTE not in str(fetched.stderr or ""):
        raise AdoptRefused("fetch_failed", door.scrub(fetched.stderr))
    remote_has = fetched.returncode == 0 and door.ok("rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}")
    local_has = door.ok("rev-parse", "-q", "--verify", "HEAD")
    outcome, detail = _reconcile(door, branch, local_has=local_has, remote_has=remote_has,
                                 merge_unrelated_if_disjoint=merge_unrelated_if_disjoint)
    receipt = AdoptReceipt(outcome, url, branch, door.out("rev-parse", "HEAD"), detail)
    from .work_store.receipts import emit

    emit("git.remote_adopted", repo=Path(repo).name, outcome=outcome.value, branch=branch)
    return receipt


def _reconcile(door: _Door, branch: str, *, local_has: bool, remote_has: bool,
               merge_unrelated_if_disjoint: bool) -> tuple[Adoption, str]:
    tip = f"origin/{branch}"
    if not local_has and not remote_has:
        return Adoption.ALREADY, "empty"
    if not local_has:
        door.must("fetch_failed", "reset", "-q", "--hard", tip)
        door.ensure_upstream(branch)
        return Adoption.ADDED_FETCHED, ""
    if not remote_has:
        door.must("push_failed", "push", "-q", "-u", "origin", f"HEAD:{branch}")
        return Adoption.ADDED_PUSHED, ""
    if door.ok("merge-base", "HEAD", tip):
        door.ensure_upstream(branch)
        return Adoption.ALREADY, ""
    shared = sorted((_paths(door, "HEAD") & _paths(door, tip)) - SHARED_OK)
    if not merge_unrelated_if_disjoint or shared:
        raise AdoptRefused("remote_diverged", "unrelated histories; shared paths: " + ", ".join(shared[:20]))
    door.must("remote_diverged", "merge", "-q", "--allow-unrelated-histories", "--no-edit", "-X", "ours", tip)
    door.ensure_upstream(branch)
    return Adoption.MERGED_UNRELATED, ""
