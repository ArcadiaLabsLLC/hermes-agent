"""What this machine's next publish does to the realm's WORKSPACES, for the status read.

``realm sync status`` answered ``unpublished_changes: false`` while a workspace the member had moved
out of the realm, or deleted, was still in the team's copy: the drift walk reads boards, office,
personas, canvas, skills and levels, never the workspace files, so the leave sat in the realm's delete
ledger with nothing naming it and the member's next publish removed the workspace for everyone
(RT-REALM-STATUS-MISSES-A-WAITING-WORKSPACE-LEAVE).

The rows are the publish's own arithmetic, not a second opinion: the workspaces the publish would ship
are ``artifacts._workspaces_for_realm`` (the set ``publish_realm_sync`` stages, delete ledger already
subtracted), the team's copy is the realm subtree of this machine's sync clone, and each file is
compared the way the publish compares it (canonical bytes). One row per workspace file the publish
would add, rewrite or remove:

* ``added`` — a workspace of this realm the clone does not hold (new here, moved in, or restored);
* ``changed`` — held by both, with different bytes (a rename, an archive, an agent list);
* ``left`` — held by the clone, no longer shipped, and alive on this machine under ANOTHER realm
  (``to_realm_id`` / ``to_realm_name`` name it): the move's leave, waiting;
* ``deleted`` — held by the clone, no longer shipped, and not alive under another realm here.

A realm this clone has never published (no realm record in its subtree) has no team copy to differ
from, so it has no rows: a device-only realm must not read "unpublished".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import paths
from ..models import Realm, Workspace
from ..store import RealmStore, WorkspaceStore
from .artifacts import _workspaces_for_realm
from .git import _realm_subtree
from .models import _canonicalize_text_bytes

__layer__ = "stores"
__all__ = [
    "WORKSPACE_ADDED",
    "WORKSPACE_CHANGED",
    "WORKSPACE_DELETED",
    "WORKSPACE_LEFT",
    "workspace_file_published",
    "workspace_publish_changes",
]

WORKSPACE_ADDED = "added"
WORKSPACE_CHANGED = "changed"
WORKSPACE_LEFT = "left"
WORKSPACE_DELETED = "deleted"


def _published_dir(repo: Path, realm_id: str) -> Path:
    return _realm_subtree(repo, realm_id) / "store" / "workspaces"


def workspace_file_published(repo: Path, realm_id: str, workspace_id: str) -> bool:
    """Whether the clone's copy of the workspace file equals this machine's, compared canonically
    (the published file is LF, the store file CRLF on Windows). The ONE compare behind the
    per-workspace ``published`` / ``unpublished`` state and the ``changed`` row."""

    published = _published_dir(repo, realm_id) / f"{paths.safe_path_token(workspace_id)}.json"
    try:
        return published.exists() and _canonicalize_text_bytes(published.read_bytes()) == _canonicalize_text_bytes(
            paths.workspace_path(workspace_id).read_bytes()
        )
    except OSError:
        return False


def _published_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _realm_name(realm_id: str | None) -> str | None:
    if not realm_id:
        return None
    try:
        return RealmStore().get(realm_id).name
    except Exception:  # a realm this machine no longer holds still gets its row, by id
        return None


def _alive_elsewhere(workspace_id: str, realm: Realm) -> Workspace | None:
    """The workspace as this machine holds it under a realm other than ``realm``, else None."""

    if not workspace_id or not paths.workspace_path(workspace_id).exists():
        return None
    try:
        workspace = WorkspaceStore().get(workspace_id)
    except Exception:
        return None
    return workspace if workspace.realm_id and workspace.realm_id != realm.id else None


def workspace_publish_changes(realm: Realm, repo: Path) -> list[dict[str, Any]]:
    """The module docstring's rows, sorted by workspace id; ``[]`` for a realm this clone never published."""

    subtree = _realm_subtree(repo, realm.id)
    if not (subtree / "store" / "realms" / f"{paths.safe_path_token(realm.id)}.json").exists():
        return []
    shipped = {paths.safe_path_token(workspace.id): workspace for workspace in _workspaces_for_realm(realm)}
    published_dir = _published_dir(repo, realm.id)
    held = {path.stem: path for path in published_dir.glob("*.json")} if published_dir.is_dir() else {}

    def _row(workspace_id: str, name: str, change: str, moved_to: Workspace | None = None) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "name": name,
            "change": change,
            "realm_id": realm.id,
            "realm_name": realm.name,
            "to_realm_id": moved_to.realm_id if moved_to is not None else None,
            "to_realm_name": _realm_name(moved_to.realm_id) if moved_to is not None else None,
        }

    rows: list[dict[str, Any]] = []
    for token, workspace in shipped.items():
        if token not in held:
            rows.append(_row(workspace.id, workspace.name, WORKSPACE_ADDED))
        elif not workspace_file_published(repo, realm.id, workspace.id):
            rows.append(_row(workspace.id, workspace.name, WORKSPACE_CHANGED))
    for token, path in held.items():
        if token in shipped:
            continue
        record = _published_record(path)
        workspace_id = str(record.get("id") or token)
        moved_to = _alive_elsewhere(workspace_id, realm)
        name = moved_to.name if moved_to is not None else str(record.get("name") or workspace_id)
        rows.append(_row(workspace_id, name, WORKSPACE_LEFT if moved_to is not None else WORKSPACE_DELETED, moved_to))
    return sorted(rows, key=lambda row: row["workspace_id"])
