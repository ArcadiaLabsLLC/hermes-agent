"""The workspace's content: its five categories, its guidance and the share rule (RT-WS-ABSORB-CONTENT-DOC).

Plan ``EterniaLauncher/docs/mission_control/planned/WORKSPACE_ABSORBS_PROJECTS_2026-11-04.md`` §3: the
workspace is the one record, and everything that merges key by key lives in its slot document
(``store/workspace_slots/<ws>.json``, family ``WORKSPACE_SLOTS``) beside its slots and machine reports.

* ``categories.<chats | documents | boards | artifacts | guidance>`` is a FOLDER DECLARATION, never
  content: ``slot`` names one of the workspace's slots (``None`` = no folder yet) and ``subpath`` a
  folder under it (default ``.eternia/<category>``). A category is source-controlled iff its slot has a
  clone URL; ``shared`` may be true only then (``category_not_source_controlled``, the owner's rule,
  enforced at the write and re-enforced after a declare and after a merge by :func:`enforce_share_rule`).
  ``documents`` may carry ``context_files``: the files offered as context, relative to its folder.
* ``guidance`` has no folder: it is the workspace's description + instructions, carried in the document
  ONLY while ``categories.guidance.shared`` is true, so unshared guidance never syncs (it stays in the
  account's workspace overlay, launcher-side).

Every write passes the realm PUBLISH decision of the workspace's realm (``require_publish_right``),
exactly like ``runtime.workspace.slots.declare``.
The record helpers (:func:`category`, :func:`source_controlled`, :func:`enforce_share_rule`,
:func:`apply_category`, :func:`apply_guidance`) are pure over a record dict.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .workspace_slots import (
    REASON_INVALID_DECLARATION,
    REASON_SLOT_NOT_DECLARED,
    SlotRefused,
    _inside_checkout,
    live_slots,
    load_document,
    refuse_stale,
    require_publish_right,
    write_document,
)

__layer__ = "stores"

#: The four categories that are a folder inside one of the workspace's slots.
FOLDER_CATEGORIES = ("chats", "documents", "boards", "artifacts")
#: The fifth category: description + instructions, in the document, its own switch.
GUIDANCE = "guidance"
CATEGORIES = (*FOLDER_CATEGORIES, GUIDANCE)
CHATS, DOCUMENTS, BOARDS, ARTIFACTS = FOLDER_CATEGORIES
#: The launcher's instructions bound, and the description's.
GUIDANCE_MAX_CHARS = 32000
#: The artifacts listing's bound; a folder past it answers ``truncated: true`` (never a silent cap).
ARTIFACTS_LIST_LIMIT = 2000

REASON_UNKNOWN_CATEGORY = "unknown_category"
REASON_CATEGORY_NOT_SOURCE_CONTROLLED = "category_not_source_controlled"
REASON_GUIDANCE_NOT_SHARED = "guidance_not_shared"
REASON_GUIDANCE_TOO_LONG = "guidance_too_long"


# ── the record helpers (pure) ────────────────────────────────────────────────


def source_controlled(record: dict[str, Any], slot: Any) -> bool:
    """True when ``slot`` is a live slot of the record with a clone URL (not ``repo.local``)."""

    held = live_slots(record).get(slot) if isinstance(slot, str) else None
    repo = (held or {}).get("repo") or {}
    return bool(repo.get("clone_url")) and not repo.get("local")


def category(record: dict[str, Any], name: str) -> dict[str, Any]:
    """The category's declaration, or the unset default (no folder, not shared)."""

    held = (record.get("categories") or {}).get(name)
    if isinstance(held, dict):
        return held
    return {"slot": None, "subpath": None if name == GUIDANCE else f".eternia/{name}", "shared": False,
            "issued_at": None, "revision": 0}


def enforce_share_rule(record: dict[str, Any]) -> list[str]:
    """Unshare every folder category whose slot is not source-controlled; drop unshared guidance.

    Runs after a declare (a slot made local or removed) and after a merge (a peer's share beside a
    local slot change), so the owner's rule holds for the record whatever wrote it. Returns the
    categories it unshared.
    """

    unshared = []
    for name, held in sorted((record.get("categories") or {}).items()):
        if name in FOLDER_CATEGORIES and isinstance(held, dict) and held.get("shared") \
                and not source_controlled(record, held.get("slot")):
            record["categories"][name] = {**held, "shared": False}
            unshared.append(name)
    if not category(record, GUIDANCE).get("shared"):
        record.pop("guidance", None)
    return unshared


def apply_category(record: dict[str, Any], name: str, *, slot: Any, subpath: Any, shared: Any, issued_at: str,
                   context_files: Any = None, owner: str = "") -> dict[str, Any]:
    """Declare one category's folder and its share switch in ``record``, in place; the category as it was.

    ``context_files`` (documents only) REPLACES the files offered as context, relative to the folder;
    ``None`` keeps the list the record holds. ``stale_revision`` when ``issued_at`` is older than the
    category's last write.
    """

    if name not in CATEGORIES:
        raise SlotRefused(REASON_UNKNOWN_CATEGORY, str(name))
    if not isinstance(shared, bool):
        raise SlotRefused(REASON_INVALID_DECLARATION, "shared is a boolean")
    held = category(record, name)
    refuse_stale(held.get("issued_at"), issued_at)
    if name == GUIDANCE:
        slot, subpath = None, None
    else:
        if slot is not None and slot not in live_slots(record):
            raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{owner} declares no slot {slot!r}")
        subpath = f".eternia/{name}" if subpath in (None, "") else subpath
        if not _inside_checkout(subpath):
            raise SlotRefused(REASON_INVALID_DECLARATION, "subpath is a relative path inside the slot")
        if shared and not source_controlled(record, slot):
            raise SlotRefused(REASON_CATEGORY_NOT_SOURCE_CONTROLLED,
                              f"{name} sits in no source-controlled slot; only a cloned slot is shared")
    extra = {k: v for k, v in held.items() if k not in {"slot", "subpath", "shared", "issued_at", "revision"}}
    if context_files is not None:
        if name != DOCUMENTS:
            raise SlotRefused(REASON_INVALID_DECLARATION, "context_files belong to the documents category")
        if not isinstance(context_files, list) or not all(_inside_checkout(f) for f in context_files):
            raise SlotRefused(REASON_INVALID_DECLARATION, "context_files are relative paths inside the folder")
        extra["context_files"] = list(dict.fromkeys(context_files))
    record.setdefault("categories", {})[name] = {
        **extra, "slot": slot, "subpath": subpath, "shared": shared, "issued_at": issued_at,
        "revision": int(held.get("revision") or 0) + 1}
    return held


def apply_guidance(record: dict[str, Any], *, description: Any, instructions: Any, issued_at: str) -> dict[str, Any]:
    """The description + instructions into ``record``, in place; refused ``guidance_not_shared`` while the switch is off."""

    held = record.get("guidance") if isinstance(record.get("guidance"), dict) else {}
    refuse_stale((held or {}).get("issued_at"), issued_at)
    if not category(record, GUIDANCE).get("shared"):
        raise SlotRefused(REASON_GUIDANCE_NOT_SHARED, "turn the guidance share on before writing it")
    texts = {"description": description or "", "instructions": instructions or ""}
    for key, value in texts.items():
        if not isinstance(value, str):
            raise SlotRefused(REASON_INVALID_DECLARATION, f"{key} is text")
        if len(value) > GUIDANCE_MAX_CHARS:
            raise SlotRefused(REASON_GUIDANCE_TOO_LONG, f"{key} is over {GUIDANCE_MAX_CHARS} characters")
    record["guidance"] = {**texts, "issued_at": issued_at, "revision": int((held or {}).get("revision") or 0) + 1}
    return record["guidance"]


# ── the workspace's writes ───────────────────────────────────────────────────


def set_category(workspace_id: str, name: str, *, slot: Any, subpath: Any, shared: Any, issued_at: str,
                 context_files: Any = None, credential: Any = None) -> dict[str, Any]:
    """``runtime.workspace.category.set``: one category of the workspace's slot document.

    Unsharing the chats drops the workspace's shared chat store and nothing else (its git folder,
    every agent's own ``state.db`` and every other workspace's store stay).
    """

    require_publish_right(workspace_id, credential)
    document = load_document(workspace_id)
    held = apply_category(document, name, slot=slot, subpath=subpath, shared=shared, issued_at=issued_at,
                          context_files=context_files, owner=workspace_id)
    enforce_share_rule(document)
    document["workspace_id"] = workspace_id
    write_document(workspace_id, document)
    if name == CHATS and held.get("shared") and not shared:
        from .project_chat_fold import drop_chats
        from .project_chat_export import ChatHome

        drop_chats(ChatHome.workspace(workspace_id), reason="chats_unshared")
    return {"workspace_id": workspace_id, "category": name, "record": document["categories"][name]}


def set_guidance(workspace_id: str, *, description: Any, instructions: Any, issued_at: str,
                 credential: Any = None) -> dict[str, Any]:
    """``runtime.workspace.guidance.set``: the workspace's shared description + instructions."""

    require_publish_right(workspace_id, credential)
    document = load_document(workspace_id)
    guidance = apply_guidance(document, description=description, instructions=instructions, issued_at=issued_at)
    document["workspace_id"] = workspace_id
    write_document(workspace_id, document)
    return {"workspace_id": workspace_id, "guidance": guidance}


# ── the folders on THIS machine ──────────────────────────────────────────────


def category_folder(workspace_id: str, name: str, document: dict[str, Any] | None = None) -> Path | None:
    """This machine's folder for a workspace category: the slot's fill / ``subpath``, or None when it has none here."""

    from .workspace_slots import scoped_roots

    document = load_document(workspace_id) if document is None else document
    return folder_under(category(document, name), live_slots(document),
                        lambda slot: scoped_roots().workspace_root(workspace_id, slot))


def folder_under(held: dict[str, Any], live: dict[str, Any], root_of) -> Path | None:
    """The folder a category declaration names under ``root_of(slot)``, when it exists on this machine."""

    slot, subpath = held.get("slot"), held.get("subpath")
    if not isinstance(slot, str) or slot not in live or not _inside_checkout(subpath):
        return None
    root = root_of(slot)
    folder = root / subpath if root is not None else None
    return folder if folder is not None and folder.is_dir() else None


def list_folder(folder: Path | None) -> dict[str, Any]:
    """``{here, files: [{name, size}], truncated}`` for an artifacts folder; hermes never writes there."""

    if folder is None:
        return {"here": False, "files": [], "truncated": False}
    files: list[dict[str, Any]] = []
    truncated = False
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if len(files) >= ARTIFACTS_LIST_LIMIT:
                truncated = True
                break
            path = Path(root) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            files.append({"name": path.relative_to(folder).as_posix(), "size": size})
        if truncated:
            break
    return {"here": True, "files": files, "truncated": truncated}


def artifacts_list(workspace_id: str) -> dict[str, Any]:
    """``runtime.workspace.artifacts.list``: the artifacts folder's files on this machine."""

    return {"workspace_id": workspace_id, **list_folder(category_folder(workspace_id, ARTIFACTS))}


__all__ = [
    "ARTIFACTS",
    "BOARDS",
    "CATEGORIES",
    "CHATS",
    "DOCUMENTS",
    "FOLDER_CATEGORIES",
    "GUIDANCE",
    "GUIDANCE_MAX_CHARS",
    "apply_category",
    "apply_guidance",
    "artifacts_list",
    "category",
    "category_folder",
    "enforce_share_rule",
    "folder_under",
    "list_folder",
    "set_category",
    "set_guidance",
    "source_controlled",
]
