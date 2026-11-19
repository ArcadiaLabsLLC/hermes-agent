"""Whether this machine's STORE has adopted what its realm sync clone holds.

The clone and the store move in two steps. ``_ensure_sync_repo`` (every sync verb) clones, and a pull's
``_pull_remote_into_repo`` fast-forwards or merges the team's commits into the clone; only then do the
pull's appliers adopt those documents into the store. A pull whose appliers did not finish, or a clone a
status read made before any pull, leaves git reading ``behind: 0`` while the store still holds the old
documents. Every store-vs-clone compare then names the teammate's change as this machine's, and a publish
(refused only when git is behind) writes the old store over the team's newer commit
(RT-REALM-STATUS-READS-AN-UNADOPTED-PULL-AS-UNPUBLISHED, reproduced 2026-11-18).

The answer is one marker, the clone commit the store last adopted, in the clone's ``.git/hermes``
beside ``last_pull.txt`` / ``last_publish.txt``:

* a pull records it after EVERY applier finished (:func:`record_adopted_head`);
* a publish records it right after its own commit, whose subtree IS the store's export;
* the store has adopted the clone when the newest TEAM commit touching this realm's subtree is that marker
  or one of its ancestors. A team commit is one the clone shares with its upstream (reachable from
  ``merge-base HEAD @{u}``): this machine's own commits not yet pushed are its store's export, and a clone
  with no upstream has nothing from the team. Another realm's commit in a shared personal repo never
  counts, and a subtree no team commit touched has nothing to adopt.

A clone from before the marker existed has none: it is adopted when its last finished pull or publish is
no older than the newest commit touching the subtree (``last_pull.txt`` is written only at the end of a
pull that finished), and a clone with neither stamp, made by a read before any pull, is not.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import paths
from .git import sync_git
from .sidecar import _timestamp_file

__layer__ = "stores"
__all__ = ["ADOPTED_HEAD_FILE", "record_adopted_head", "store_adopted"]

ADOPTED_HEAD_FILE = "adopted_head.txt"


def _marker(repo: Path) -> Path:
    return repo / ".git" / "hermes" / ADOPTED_HEAD_FILE


def record_adopted_head(repo: Path) -> None:
    """The clone's HEAD is now what the store holds (a finished pull, or a publish's own commit)."""

    head = sync_git(repo).resolve("HEAD")
    if not head:
        return
    path = _marker(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head, encoding="utf-8")


def _when(stamp: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None


def _legacy_adopted(repo: Path, subtree: str, shared: str) -> bool:
    entries = sync_git(repo).log([shared], subtree, 1)
    newest_at = _when(entries[0].at) if entries else None
    stamps = [_when(_timestamp_file(repo, name)) for name in ("last_pull.txt", "last_publish.txt")]
    finished = [stamp for stamp in stamps if stamp is not None]
    if not finished:
        return False
    if newest_at is None:
        return True
    try:
        return max(finished) >= newest_at
    except TypeError:  # one stamp naive, one aware: the stamps exist, so the clone was synced here
        return True


def store_adopted(repo: Path, realm_id: str) -> bool:
    """The module docstring's answer for ``realm_id``'s subtree of ``repo``."""

    git = sync_git(repo)
    if not (repo / ".git").exists() or git.resolve("HEAD") is None:
        return True
    upstream = git.upstream()
    shared = git.merge_base("HEAD", upstream) if upstream else None
    if shared is None:
        return True
    subtree = f"realms/{paths.safe_path_token(realm_id)}"
    newest = git.newest(shared, subtree)
    if newest is None:
        return True
    try:
        marker = _marker(repo).read_text(encoding="utf-8").strip()
    except OSError:
        return _legacy_adopted(repo, subtree, shared)
    return newest == marker or git.is_ancestor(newest, marker)
