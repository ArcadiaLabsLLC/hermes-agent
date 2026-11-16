"""The named git steps realm sync asks for: one contract, answered by a backend per call.

Realm sync used to build git argv and parse git's text at every call site. Every
call site now asks this port for a named step and gets a typed answer, so a second
git (the pure-Python one a phone carries, plan
``docs/agent-runtime-harness/planned/phone-realm-sync-dulwich-2026-11-16.md`` §3) can
answer the same steps without re-rendering git's porcelain, log or stderr text.

This module owns the verb CONTRACT and nothing else: which backend answers is
``git.sync_git_backend()`` alone, and each backend is its own module
(``git_binary`` runs today's git program). A verb that fails raises the
``RealmSyncError`` the sync verbs already carry (``sync_remote_unreachable``,
``sync_auth_failed``) with ``safe_details`` free of any credential.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

__layer__ = "models"
__all__ = [
    "ChangedPath",
    "FetchOutcome",
    "LogEntry",
    "MergeOutcome",
    "PushOutcome",
    "PushReport",
    "RepoState",
    "SyncGit",
]


@dataclass(frozen=True, slots=True)
class RepoState:
    """Where the clone stands against its upstream (or, with none, against every remote)."""

    ahead: int
    behind: int
    conflicts: tuple[str, ...]
    dirty: bool

    def as_dict(self) -> dict[str, Any]:
        """The shape the sync envelopes and the sidecar have always carried."""

        return {"ahead": self.ahead, "behind": self.behind, "conflicts": list(self.conflicts), "dirty": self.dirty}


@dataclass(frozen=True, slots=True)
class ChangedPath:
    """One path the working tree or index holds differently from ``HEAD``."""

    path: str
    untracked: bool


class PushOutcome(Enum):
    PUSHED = "pushed"
    #: The remote moved past us (another member published first): pull, then publish again.
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PushReport:
    outcome: PushOutcome
    #: For ``REJECTED``: what the refusal may show (scrubbed), as a failed step's ``safe_details``.
    safe_details: Mapping[str, Any] = field(default_factory=dict)


class FetchOutcome(Enum):
    FETCHED = "fetched"
    #: The remote has no such branch yet (an empty repository).
    EMPTY_REMOTE = "empty_remote"


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    """A merge that ran: empty ``conflicts`` means it committed."""

    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LogEntry:
    sha: str
    at: str  # ISO 8601, the author date
    author: str
    paths: tuple[str, ...]  # repository-relative paths the commit changed


class SyncGit(Protocol):
    """The steps realm sync takes on ONE repository (``repo``), whichever git answers them."""

    # -- the repository and its remotes ------------------------------------------------------
    def init(self) -> None: ...
    def clone(self, url: str, auth: RealmSyncCredential | None) -> None:
        """Make ``repo`` a clone of ``url`` (``repo`` does not exist yet)."""
    def remote_url(self, name: str) -> str | None: ...
    def remotes(self) -> tuple[str, ...]: ...
    def remote_add(self, name: str, url: str) -> None: ...
    def remote_remove(self, name: str, *, missing_ok: bool = False) -> None:
        """Drop the remote AND its tracking refs (a stale one would read as the next remote's tip)."""
    def has_remote_refs(self) -> bool: ...

    # -- branches and refs -------------------------------------------------------------------
    def current_branch(self) -> str | None: ...
    def rename_branch(self, branch: str) -> None:
        """Name the checked-out branch ``branch`` (moving it, or only HEAD while it has no commit)."""
    def resolve(self, ref: str) -> str | None:
        """The commit ``ref`` names, or ``None`` when it names none."""
    def upstream(self) -> str | None:
        """The branch's upstream as ``<remote>/<branch>``, or ``None``."""
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...

    # -- the working tree and the index ------------------------------------------------------
    def is_tracked(self, path: str) -> bool: ...
    def state(self) -> RepoState: ...
    def changed(self, paths: Sequence[str] = (), *, untracked_all: bool = False) -> tuple[ChangedPath, ...]: ...
    def add(self, paths: Sequence[str]) -> None: ...
    def commit(self, message: str, trailers: Sequence[str] = ()) -> None:
        """Commit the index as ``SYNC_IDENTITY``; each trailer is its own paragraph."""

    # -- the network -------------------------------------------------------------------------
    def fetch(self, auth: RealmSyncCredential | None) -> FetchOutcome: ...
    def pull_fast_forward(self, auth: RealmSyncCredential | None) -> None: ...
    def merge_remote_theirs(self, auth: RealmSyncCredential | None) -> MergeOutcome:
        """Fetch and merge the upstream; where both sides changed the same lines the remote wins."""
    def push(self, auth: RealmSyncCredential | None, *, set_upstream: bool) -> PushReport: ...

    # -- history -----------------------------------------------------------------------------
    def log(self, refs: Sequence[str], subtree: str, limit: int) -> list[LogEntry]:
        """Commits reachable from ``refs`` that touch ``subtree``, newest first (date order)."""
    def newest(self, ref: str, subtree: str) -> str | None: ...
