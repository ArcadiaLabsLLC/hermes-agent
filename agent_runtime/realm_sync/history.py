"""``realm sync history`` — the realm's published versions, read from the local clone (H1).

Every publish is one commit of ``realms/<realm>/`` in the sync repo, so the durable
history is ``git log`` over that subtree. This verb reads it and nothing else: no
fetch (``realm sync status`` is the freshness step and reports ``remote_checked``),
no credential, no store write. Newest first, across this machine's ``HEAD`` and the
remote-tracking ``@{u}`` when there is one, so a version a member published that
this machine has not pulled is listed too.

Each row: ``{sha, at, author, changed_paths, is_local_head, is_upstream_head}``.
``changed_paths`` are ``{family, container, item_key, path}`` — mapped by
:data:`_ITEM_SHAPES` (one table, path prefix -> how to read container and key), so a
row names the same ``family`` / ``container`` / ``item_key`` a store-drift row does
where the published path carries them. A whole-document family (``personas.yaml``,
``persona_instances.yaml``, ``flow_graphs.yaml``) is one item keyed by the document:
which records inside it moved is a content diff this read does not take.
``is_local_head`` marks the newest version this machine's ``HEAD`` holds ("Yours");
``is_upstream_head`` the newest the remote-tracking ref holds ("Latest").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_runtime import paths
from agent_runtime.realm_sync.drift import DRIFT_KEY_BOARD_DEF, DRIFT_KEY_OFFICE_SURFACE
from agent_runtime.realm_sync.families import SyncFamily, _kind_for_sync_path
from agent_runtime.realm_sync.git import _git, _sync_repo_path
from agent_runtime.store import RealmStore

__layer__ = "lanes"

__all__ = ["DEFAULT_HISTORY_LIMIT", "realm_sync_history"]

DEFAULT_HISTORY_LIMIT = 50
_MAX_HISTORY_LIMIT = 500

#: Separators ``git log --format`` writes between records and fields (ASCII RS / US),
#: which no sha, date or author name carries.
_RECORD, _FIELD = "\x1e", "\x1f"


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0] if "." in name else name


@dataclass(frozen=True, slots=True)
class _ItemShape:
    """How a published path under ``prefix`` names its item."""

    prefix: str
    read: Callable[[tuple[str, ...]], tuple[str, str, str] | None]  # parts after prefix -> (family, container, key)


def _board(parts: tuple[str, ...]) -> tuple[str, str, str] | None:
    if len(parts) == 2 and parts[1] == "board.json":
        return SyncFamily.BOARD, parts[0], DRIFT_KEY_BOARD_DEF
    if len(parts) == 3 and parts[1] == "cards":
        return SyncFamily.BOARD_CARD, parts[0], _stem(parts[2])
    return None


def _office(parts: tuple[str, ...]) -> tuple[str, str, str] | None:
    if len(parts) == 2 and parts[1] == "office.json":
        return SyncFamily.OFFICE_SURFACE, parts[0], DRIFT_KEY_OFFICE_SURFACE
    if len(parts) == 3 and parts[1] == "actors":
        return SyncFamily.OFFICE_ACTOR, parts[0], _stem(parts[2])
    return None


def _skill(parts: tuple[str, ...]) -> tuple[str, str, str] | None:
    return (SyncFamily.SKILL, "", parts[0]) if parts else None


def _document(family: SyncFamily) -> Callable[[tuple[str, ...]], tuple[str, str, str] | None]:
    return lambda parts: (family, "", _stem(parts[-1])) if parts else None


#: Published path prefix -> item reader, first match wins. A path no row claims keeps
#: its kind from :data:`families.SYNC_PATH_FAMILIES` and is keyed by the path itself.
_ITEM_SHAPES: tuple[_ItemShape, ...] = (
    _ItemShape("store/boards/", _board),
    _ItemShape("store/office/", _office),
    _ItemShape("skills/", _skill),
    _ItemShape("store/levels/", _document(SyncFamily.LEVEL)),
    _ItemShape("store/workspace_slots/", _document(SyncFamily.WORKSPACE_SLOTS)),
    _ItemShape("store/maps/", _document(SyncFamily.MAP)),
    _ItemShape("store/personas.yaml", _document(SyncFamily.PERSONA_CONFIG)),
    _ItemShape("store/persona_instances.yaml", _document(SyncFamily.PERSONA_INSTANCE_CONFIG)),
    _ItemShape("store/flow_graphs.yaml", _document(SyncFamily.FLOW_GRAPH_CONFIG)),
)


def _changed_item(rel: str) -> dict[str, str]:
    for shape in _ITEM_SHAPES:
        if rel.startswith(shape.prefix):
            tail = rel[len(shape.prefix):] or Path(rel).name  # a whole document names itself
            found = shape.read(tuple(part for part in tail.split("/") if part))
            if found is not None:
                family, container, key = found
                return {"family": str(family), "container": container, "item_key": key, "path": rel}
    return {"family": str(_kind_for_sync_path(rel)), "container": "", "item_key": rel, "path": rel}


def _newest(repo: Path, ref: str, subtree: str) -> str | None:
    sha = _git(repo, "log", "-1", "--format=%H", ref, "--", subtree, check=False).strip()
    return sha or None


def realm_sync_history(realm_id: str, *, limit: int = DEFAULT_HISTORY_LIMIT) -> dict[str, Any]:
    """The realm's versions, newest first, from the local clone. Read-only, no fetch."""

    realm = RealmStore().get(realm_id)
    limit = max(1, min(int(limit), _MAX_HISTORY_LIMIT))
    repo = _sync_repo_path(realm)
    subtree = f"realms/{paths.safe_path_token(realm.id)}"
    envelope: dict[str, Any] = {"schema_version": 1, "id": realm.id, "kind": "realm_sync_history",
                                "limit": limit, "history": []}
    if not (repo / ".git").exists() or not _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).strip():
        return envelope
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).strip()
    refs = ["HEAD", *([upstream] if upstream else [])]
    local_head = _newest(repo, "HEAD", subtree)
    upstream_head = _newest(repo, upstream, subtree) if upstream else local_head
    log = _git(repo, "log", f"-n{limit}", f"--format={_RECORD}%H{_FIELD}%aI{_FIELD}%an", "--name-only",
               *refs, "--", subtree, check=False)
    prefix = subtree + "/"
    for record in log.split(_RECORD):
        lines = [line for line in record.splitlines() if line.strip()]
        if not lines:
            continue
        sha, at, author = (lines[0].split(_FIELD) + ["", ""])[:3]
        changed = [_changed_item(line[len(prefix):]) for line in lines[1:]
                   if line.startswith(prefix) and line != prefix + "manifest.json"]
        envelope["history"].append({
            "sha": sha, "at": at, "author": author, "changed_paths": changed,
            "changed_count": len(changed),
            "is_local_head": sha == local_head, "is_upstream_head": sha == upstream_head,
        })
    return envelope
