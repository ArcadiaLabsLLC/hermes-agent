"""The one door that gives an existing git repository its ``origin`` (p10-work plan §2.3, stage R0).

``adopt_remote(repo, url)`` is shared by the default brain's promotion (a brain repo hermes just
created on the git host: the remote is empty, or the local directory is) and the local realm's
personal repo (``REALM-LOCAL-REMOTE-FROM-CREDENTIAL``: two machines of one player may each hold
commits). Every step is a verb of the realm-sync port (``realm_sync.git_port.SyncGit``): realm sync passes
its own (``git=``, with the brokered credential as ``auth``), every other caller gets the git program's
half (``realm_sync.git_binary.BinarySyncGit``) over ``run`` with ``config`` rendered as ``-c`` pairs, so a
credential (``http.extraHeader=Authorization: …``) never touches ``.git/config``; stderr is scrubbed
before it reaches a refusal.

The step table, after ``config --get remote.origin.url`` (the raw value; equal → kept; different → ``url_mismatch``; absent
→ ``remote add``) and ``fetch origin <branch>`` (a missing branch is an EMPTY remote):

| local has commits | remote has commits | outcome |
|---|---|---|
| no | yes | ``reset --hard origin/<branch>`` + upstream → ``ADDED_FETCHED`` |
| yes | no | ``push -u origin HEAD:<branch>`` → ``ADDED_PUSHED``; with ``push_into_empty=False`` nothing is pushed → ``ADDED_UNPUBLISHED`` |
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
from typing import TYPE_CHECKING

from .git_cmd import run_git

if TYPE_CHECKING:
    from .realm_membership import RealmSyncCredential
    from .realm_sync.git_port import SyncGit

__layer__ = "stores"
__all__ = ["AdoptReceipt", "AdoptRefused", "Adoption", "adopt_remote"]

#: The one path two subtrees may both carry (the realm repo's managed file; ours wins).
SHARED_OK = frozenset({".gitattributes"})


class Adoption(StrEnum):
    ADDED_PUSHED = "added_pushed"
    ADDED_FETCHED = "added_fetched"
    ALREADY = "already"
    MERGED_UNRELATED = "merged_unrelated"
    #: The remote is empty and the caller may not publish (``push_into_empty=False``): ``origin`` is set,
    #: nothing is pushed, the local history waits for a publish (RT-REALM-SYNC-PULL-PUBLISHES-INTO-A-MOVED-REPO).
    ADDED_UNPUBLISHED = "added_unpublished"


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


#: How the git program's half runs each adopt step (no prompt, no hang past five minutes).
_RUN_KWARGS = {"encoding": "utf-8", "errors": "replace", "timeout": 300, "stdin": subprocess.DEVNULL}


class _StepFailed(Exception):
    """A port step failed; ``adopt_remote`` answers it as ``AdoptRefused(reason)``."""

    def __init__(self, reason: str, step: str, stderr: str) -> None:
        super().__init__(reason)
        self.reason, self.step, self.stderr = reason, step, stderr


def _must(reason: str, step: str, call: Callable[[], object]) -> object:
    from .realm_sync.models import RealmSyncError

    try:
        return call()
    except RealmSyncError as exc:
        raise _StepFailed(reason, step, str(exc.safe_details.get("stderr") or "")) from exc


def _ensure_upstream(git: SyncGit, branch: str) -> None:
    from .realm_sync.models import RealmSyncError

    if git.upstream() is None:
        try:
            git.set_upstream(branch)
        except RealmSyncError:
            pass


def adopt_remote(
    repo: Path,
    url: str,
    *,
    branch: str = "main",
    config: Sequence[str] = (),
    merge_unrelated_if_disjoint: bool = False,
    push_into_empty: bool = True,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_git,
    git: SyncGit | None = None,
    auth: RealmSyncCredential | None = None,
) -> AdoptReceipt:
    """Make ``url`` the ``origin`` of ``repo`` and reconcile the two histories (module docstring's table).

    Every step is a realm-sync port verb (``realm_sync.git_port.SyncGit``). Realm sync hands its own
    port in (``git``, with the brokered ``auth`` per network step), so a phone's git answers too; any
    other caller gets the git program's half, built from ``run`` and the ``config`` pairs."""

    from .realm_sync.git_binary import BinarySyncGit
    from .realm_sync.git_port import FetchOutcome

    if git is None:
        git = BinarySyncGit(Path(repo), run=run, config=config, run_kwargs=_RUN_KWARGS)
    try:
        if not git.is_repo():
            raise AdoptRefused("not_a_repo", str(Path(repo).name))
        current = git.remote_url("origin")
        if current is not None:
            if current != url:
                raise AdoptRefused("url_mismatch", "origin names another remote")
        else:
            _must("not_a_repo", "remote", lambda: git.remote_add("origin", url))
        fetched = _must("fetch_failed", "", lambda: git.fetch(auth, branch=branch))
        remote_has = fetched is FetchOutcome.FETCHED and git.resolve(f"refs/remotes/origin/{branch}") is not None
        local_has = git.resolve("HEAD") is not None
        outcome, detail = _reconcile_tips(git, branch, auth, local_has=local_has, remote_has=remote_has,
                                          merge_unrelated_if_disjoint=merge_unrelated_if_disjoint,
                                          push_into_empty=push_into_empty)
    except _StepFailed as failed:
        stderr = failed.stderr.strip()[-400:]
        raise AdoptRefused(failed.reason, f"git {failed.step}: {stderr}" if failed.step else stderr) from failed
    receipt = AdoptReceipt(outcome, url, branch, git.resolve("HEAD") or "", detail)
    from .work_store.receipts import emit

    emit("git.remote_adopted", repo=Path(repo).name, outcome=outcome.value, branch=branch)
    return receipt


def _reconcile_tips(git: SyncGit, branch: str, auth: RealmSyncCredential | None, *, local_has: bool,
                    remote_has: bool, merge_unrelated_if_disjoint: bool, push_into_empty: bool) -> tuple[Adoption, str]:
    from .realm_sync.git_port import PushOutcome

    tip = f"origin/{branch}"
    if not local_has and not remote_has:
        return Adoption.ALREADY, "empty"
    if not local_has:
        _must("fetch_failed", "reset", lambda: git.reset_hard(tip))
        _ensure_upstream(git, branch)
        return Adoption.ADDED_FETCHED, ""
    if not remote_has:
        if not push_into_empty:
            return Adoption.ADDED_UNPUBLISHED, "local history not pushed"
        report = _must("push_failed", "push", lambda: git.push(auth, set_upstream=True, branch=branch))
        if report.outcome is not PushOutcome.PUSHED:
            raise _StepFailed("push_failed", "push", str(report.safe_details.get("stderr") or ""))
        return Adoption.ADDED_PUSHED, ""
    if git.merge_base("HEAD", tip) is not None:
        _ensure_upstream(git, branch)
        return Adoption.ALREADY, ""
    shared = sorted((git.tree_paths("HEAD") & git.tree_paths(tip)) - SHARED_OK)
    if not merge_unrelated_if_disjoint or shared:
        raise AdoptRefused("remote_diverged", "unrelated histories; shared paths: " + ", ".join(shared[:20]))
    _must("remote_diverged", "merge", lambda: git.merge_unrelated_ours(tip))
    _ensure_upstream(git, branch)
    return Adoption.MERGED_UNRELATED, ""
