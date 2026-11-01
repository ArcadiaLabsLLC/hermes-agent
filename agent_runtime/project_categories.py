"""A Project's category folders as hermes READS them (H-P4, plan project-slots-and-shared-chats §7).

A category is a folder declaration in the Project record (``project_store``): ``slot`` + ``subpath``.
Its folder on THIS machine is the slot's fill joined with the subpath (:func:`category_folder`);
an unset slot, an unbound slot or a missing folder is ``None`` and every reader below says so in
its receipt rather than reading anything else.

* ``documents``: the folder offered as context. Only the files the record's ``context_files`` names
  (relative paths the launcher's selected-context list wrote through ``runtime.project.category.set``)
  load, each as its own section headed ``<project name>/documents — <file>``; an unlisted file never
  loads, however it is named.
* ``guidance``: the Project's description + instructions, one section headed by the Project name,
  only while the guidance share is on (the record carries the text only then).
* ``boards``: every live slot of every Project lists a Work board (``work_store.board.declared_boards``
  reads :func:`board_slots`), keyed by ``(project, slot)``; the category's slot is the Project's
  DEFAULT board — listed first under it, where a slot-less ``runtime.work.start`` and the default
  brain's rows land — never a filter (RT-WORK-BOARD-PER-PROJECT-SLOT). A migrated document lists none
  of its own — one publisher per board.
* ``artifacts``: hermes only LISTS the folder (``runtime.project.artifacts.list``: relative names and
  byte sizes); the launcher writes there, hermes never does.

Each reader runs for the Projects the instance's WORKSPACE holds (``Workspace.project_ids``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, NamedTuple

from .project_store import GUIDANCE, category, load_project, valid_project_id
from .workspace_slots import _inside_checkout, live_slots

__layer__ = "stores"

DOCUMENTS = "documents"
BOARDS = "boards"
ARTIFACTS = "artifacts"
#: The artifacts listing's bound; a folder past it answers ``truncated: true`` (never a silent cap).
ARTIFACTS_LIST_LIMIT = 2000


def category_folder(project_id: str, name: str, record: dict[str, Any] | None = None) -> Path | None:
    """This machine's folder for a category: the slot's fill / ``subpath``, or None when it has none here."""

    from .workspace_slots import bound_path

    record = load_project(project_id) if record is None else record
    held = category(record, name)
    slot, subpath = held.get("slot"), held.get("subpath")
    if not isinstance(slot, str) or slot not in live_slots(record) or not _inside_checkout(subpath):
        return None
    root = bound_path(slot, project_id=project_id)
    folder = root / subpath if root is not None else None
    return folder if folder is not None and folder.is_dir() else None


def _label(record: dict[str, Any], project_id: str) -> str:
    return str(record.get("name") or "").strip() or project_id


def project_context(workspace_id: str) -> tuple[list[tuple[str, str, str]], list[dict[str, Any]]]:
    """``(sections, receipts)`` of every Project the workspace holds: documents' listed files, then guidance.

    A section is ``(heading slot, file, content)`` — :class:`persona_slots.SlotContextSection`'s fields.
    """

    from .errors import NotFound
    from .prompt_observability.workspace_agents import load_workspace_agents_context
    from .store import WorkspaceStore

    try:
        held = WorkspaceStore().get(workspace_id).project_ids
    except NotFound:
        return [], []
    sections: list[tuple[str, str, str]] = []
    receipts: list[dict[str, Any]] = []
    for project_id in held:
        record = load_project(project_id)
        label = _label(record, project_id)
        listed = [f for f in (category(record, DOCUMENTS).get("context_files") or []) if _inside_checkout(f)]
        folder = category_folder(project_id, DOCUMENTS, record) if listed else None
        for file in listed:
            base = {"project_id": project_id, "category": DOCUMENTS, "file": file, "kind": "project_context",
                    "label": f"{label}/documents/{file}"}
            if folder is None:
                receipts.append({**base, "included": False, "status": "folder_not_here"})
                continue
            loaded = load_workspace_agents_context(str(folder / file), allowed_names=None)
            receipt = dict(getattr(loaded, "receipt", None) or {})
            receipt.pop("preview", None)
            receipts.append({**receipt, **base})
            if getattr(loaded, "content", None):
                sections.append((f"{label}/documents", file, loaded.content))
        guidance = record.get("guidance") if category(record, GUIDANCE).get("shared") else None
        if isinstance(guidance, dict) and (guidance.get("description") or guidance.get("instructions")):
            text = "\n\n".join(part for part in (guidance.get("description"), guidance.get("instructions")) if part)
            sections.append((label, "guidance", text))
            receipts.append({"project_id": project_id, "category": GUIDANCE, "kind": "project_context",
                             "label": f"{label}/guidance", "included": True, "status": "loaded",
                             "revision": guidance.get("revision")})
    return sections, receipts


class BoardSlot(NamedTuple):
    """One live slot a workspace lists a Work board for, with its owner (None: the workspace's own)."""

    project_id: str | None
    slot: str
    declaration: dict[str, Any]
    #: The owning Project's name (``_label``), None for the workspace's own.
    project_name: str | None = None
    #: The slot is its Project's default board (the ``boards`` category, D1 of the launcher plan
    #: workspace-todo-all-projects-2026-10-31).
    project_default: bool = False


def board_slots(workspace_id: str) -> list[BoardSlot]:
    """Every live slot the workspace sees, one entry per ``(owner, slot)``: its own document's, then each Project's.

    The ``boards`` category no longer filters (RT-WORK-BOARD-PER-PROJECT-SLOT): it names the Project's
    DEFAULT board (``project_default``), the one a slot-less ``runtime.work.start`` and the default
    brain's move pick first. Two owners of one name are both listed; ``work_store.board.declared_boards``
    keys them by ``(project, slot)`` and merges the two that name one checkout.
    """

    from .workspace_slots import load_document, slots_of_workspace

    out: list[BoardSlot] = []
    records: dict[str, dict[str, Any]] = {}
    for project_id, name in slots_of_workspace(workspace_id):
        if project_id is None:
            out.append(BoardSlot(None, name, live_slots(load_document(workspace_id))[name]))
            continue
        record = records.setdefault(project_id, load_project(project_id))
        chosen = category(record, BOARDS).get("slot")
        out.append(BoardSlot(project_id, name, live_slots(record)[name], _label(record, project_id), name == chosen))
    return out


def artifacts_list(project_id: str) -> dict[str, Any]:
    """The artifacts folder's files on this machine: ``{files: [{name, size}], here, truncated}``."""

    record = load_project(valid_project_id(project_id))
    folder = category_folder(project_id, ARTIFACTS, record)
    if folder is None:
        return {"project_id": project_id, "here": False, "files": [], "truncated": False}
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
    return {"project_id": project_id, "here": True, "files": files, "truncated": truncated}
