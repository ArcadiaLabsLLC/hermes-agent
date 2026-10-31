"""The PROJECT realm-sync family: a Project record, merged by the slot document's rules (H-P1).

Plan ``docs/agent-runtime-harness/planned/project-slots-and-shared-chats-2026-10-29.md`` §2.
``slots`` and ``machines`` merge exactly as ``workspace_slots_sync.merge_documents`` merges a
workspace slot document (names union, newer ``recipe.revision`` then newer ``issued_at`` per slot,
tombstones, ``machines`` disjoint by id and this machine's own key authored here only), and a
peer's slots and machine reports are validated by the SAME ``held_document`` before they merge —
a malformed peer slot drops whole, a malformed step drops alone, a future stamp is not believed.

What the slot document does not have is merged here:

* ``categories.<name>``: one side's whole declaration, the newer ``revision`` then the newer
  ``issued_at`` — a folder declaration is one decision, never spliced. A peer entry that is not a
  known category, or whose slot / subpath / switch / stamps fail, drops ALONE (``invalid_category``).
* ``guidance``: the newer ``revision`` wins whole; text past ``GUIDANCE_MAX_CHARS`` or a non-text
  field drops it (``invalid_guidance``).
* ``name``: the side whose document ``issued_at`` is newer.

After the merge ``project_store.enforce_share_rule`` runs, so a peer's share beside a local slot
made local (or removed) cannot leave a non-source-controlled category shared, and guidance stays
only while its switch is on. Publish copies the record verbatim; this applier is the only writer
on pull (the generic overwrite loop never touches ``store/projects/``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import paths
from .project_store import (
    CATEGORIES,
    GUIDANCE,
    GUIDANCE_MAX_CHARS,
    NAME_MAX_CHARS,
    PROJECT_SCHEMA_VERSION,
    enforce_share_rule,
    stamp_order,
    valid_migration_origin,
    valid_root_name,
    write_project,
)
from .workspace_slots import _inside_checkout, known_machine_id, load_document_from, stamp_in_future
from .workspace_slots_sync import WorkspaceSlotsPullSummary, held_document, merge_documents

__layer__ = "stores"

PUBLISHED_ROOT = "store/projects"

REASON_DOCUMENT_MALFORMED = "project_document_malformed"
#: The record's ``project_id`` does not own the file name it was published under.
REASON_DOCUMENT_MISFILED = "project_document_misfiled"
REASON_INVALID_CATEGORY = "invalid_category"
REASON_INVALID_GUIDANCE = "invalid_guidance"
REASON_INVALID_MIGRATED_FROM = "invalid_migrated_from"


def _rank(entry: dict[str, Any]) -> tuple[int, float]:
    revision = entry.get("revision")
    return (revision if type(revision) is int else 0), stamp_order(entry.get("issued_at"))


def _newer(a: Any, b: Any) -> Any:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return a if not isinstance(b, dict) else b
    return b if _rank(b) > _rank(a) else a


def merge_projects(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """The key-wise merge of two Project records (pure apart from the share rule it re-applies)."""

    base = merge_documents(local, remote)
    categories = {}
    local_categories, remote_categories = local.get("categories") or {}, remote.get("categories") or {}
    for name in sorted(set(local_categories) | set(remote_categories)):
        categories[name] = _newer(local_categories.get(name), remote_categories.get(name))
    newer_side = remote if stamp_order(remote.get("issued_at")) > stamp_order(local.get("issued_at")) else local
    merged = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "project_id": local.get("project_id") or remote.get("project_id"),
        "name": newer_side.get("name") or local.get("name") or remote.get("name") or "",
        "issued_at": base["issued_at"],
        "slots": base["slots"],
        "categories": categories,
        "machines": base["machines"],
    }
    guidance = _newer(local.get("guidance"), remote.get("guidance"))
    if isinstance(guidance, dict):
        merged["guidance"] = guidance
    # Set once by the slot migration and never edited: either side's record, the local one first.
    origin = valid_migration_origin(local.get("migrated_from")) or valid_migration_origin(remote.get("migrated_from"))
    if origin is not None:
        merged["migrated_from"] = origin
    enforce_share_rule(merged)
    return merged


# ── a peer's record, validated entry by entry ────────────────────────────────


def _held_category(name: str, entry: Any, now: float) -> dict[str, Any] | None:
    """One peer category declaration rebuilt from its checked fields, or None (drop it)."""

    if name not in CATEGORIES or not isinstance(entry, dict):
        return None
    slot, subpath, shared, revision = entry.get("slot"), entry.get("subpath"), entry.get("shared"), entry.get("revision")
    issued_at = entry.get("issued_at")
    if (not (slot is None or valid_root_name(slot)) or not isinstance(shared, bool)
            or type(revision) is not int or revision < 0 or not isinstance(issued_at, (str, type(None)))
            or stamp_in_future(issued_at, now=now)):
        return None
    if name == GUIDANCE:
        if slot is not None or subpath is not None:
            return None
    elif not _inside_checkout(subpath):
        return None
    held = {"slot": slot, "subpath": subpath, "shared": shared, "issued_at": issued_at, "revision": revision}
    files = entry.get("context_files")
    if files is not None:
        if name != "documents" or not isinstance(files, list) or not all(_inside_checkout(f) for f in files):
            return None
        held["context_files"] = list(files)
    return held


def _held_guidance(entry: Any, now: float) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    texts = {key: entry.get(key) for key in ("description", "instructions")}
    revision, issued_at = entry.get("revision"), entry.get("issued_at")
    if (not all(isinstance(v, str) and len(v) <= GUIDANCE_MAX_CHARS for v in texts.values())
            or type(revision) is not int or revision < 0 or not isinstance(issued_at, (str, type(None)))
            or stamp_in_future(issued_at, now=now)):
        return None
    return {**texts, "issued_at": issued_at, "revision": revision}


def held_project(remote: dict[str, Any], *, me: str | None = None,
                 now: float | None = None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """``(record, refused)``: a peer's Project record with every invalid entry dropped."""

    now = time.time() if now is None else now
    held, refused = held_document(remote, me=me, now=now)
    categories = {}
    raw = remote.get("categories")
    for name in sorted(raw if isinstance(raw, dict) else {}, key=str):
        entry = _held_category(name, raw[name], now) if isinstance(name, str) else None
        if entry is None:
            refused.append({"category": name if name in CATEGORIES else "unknown", "reason": REASON_INVALID_CATEGORY})
            continue
        categories[name] = entry
    if raw is not None and not isinstance(raw, dict):
        refused.append({"field": "categories", "reason": REASON_INVALID_CATEGORY})
    record = {"schema_version": PROJECT_SCHEMA_VERSION, "project_id": remote.get("project_id"),
              "name": remote.get("name") if isinstance(remote.get("name"), str)
              and len(remote["name"]) <= NAME_MAX_CHARS else "",
              "issued_at": held.get("issued_at") or "", "slots": held["slots"], "categories": categories,
              "machines": held["machines"]}
    if remote.get("migrated_from") is not None:
        origin = valid_migration_origin(remote["migrated_from"])
        if origin is None:
            refused.append({"field": "migrated_from", "reason": REASON_INVALID_MIGRATED_FROM})
        else:
            record["migrated_from"] = origin
    if "guidance" in remote:
        guidance = _held_guidance(remote["guidance"], now)
        if guidance is None:
            refused.append({"field": "guidance", "reason": REASON_INVALID_GUIDANCE})
        else:
            record["guidance"] = guidance
    return record, refused


def apply_project_pull(realm_id: str, subtree: Path, *, now: float | None = None) -> WorkspaceSlotsPullSummary:
    """Merge every published Project record into this machine's copy (``now``: this machine's clock)."""

    summary = WorkspaceSlotsPullSummary()
    me, now = known_machine_id(), time.time() if now is None else now
    published = Path(subtree) / PUBLISHED_ROOT
    if not published.is_dir():
        return summary
    files = sorted(published.glob("*.json"))
    summary.source = len(files)
    for path in files:
        remote = load_document_from(path)
        if not isinstance(remote.get("slots"), dict):
            summary.refused.append({"document": path.name, "reason": REASON_DOCUMENT_MALFORMED})
            continue
        owner = remote.get("project_id")
        if not isinstance(owner, str) or not owner or paths.project_path(owner).name != path.name:
            summary.refused.append({"document": path.name, "reason": REASON_DOCUMENT_MISFILED})
            continue
        remote, refused = held_project(remote, me=me, now=now)
        summary.refused.extend({"document": path.name, **row} for row in refused)
        local_path = paths.projects_dir() / path.name
        local = load_document_from(local_path) if local_path.is_file() else {}
        merged = merge_projects(local, remote)
        if json.dumps(merged, sort_keys=True) == json.dumps(local, sort_keys=True):
            summary.unchanged.append(path.stem)
            continue
        write_project(owner, merged)
        summary.merged.append(path.stem)
        _drop_project_slots_removed_by_merge(owner, local, merged)
    return summary


def _drop_project_slots_removed_by_merge(project_id: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    """A peer's tombstone that won the merge leaves every local assignment of that slot too."""

    from .persona_slots import drop_project_slots

    was_live = {name for name, slot in (before.get("slots") or {}).items() if not (slot or {}).get("removed_at")}
    now_removed = {name for name, slot in (after.get("slots") or {}).items() if (slot or {}).get("removed_at")}
    if was_live & now_removed:
        drop_project_slots(project_id, removed=frozenset(was_live & now_removed))


def publish_artifacts(workspaces: list[Any]) -> list[Any]:
    """One artifact per Project a workspace of this realm holds, when this machine has its record."""

    from .realm_sync.families import SyncFamily
    from .realm_sync.models import RealmSyncArtifact

    artifacts = []
    for project_id in sorted({pid for ws in workspaces for pid in (getattr(ws, "project_ids", None) or [])}):
        source = paths.project_path(project_id)
        if source.is_file():
            artifacts.append(RealmSyncArtifact(kind=SyncFamily.PROJECT, source=source,
                                               relative_path=f"{PUBLISHED_ROOT}/{source.name}", destination=source))
    return artifacts
