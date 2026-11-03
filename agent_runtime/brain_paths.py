"""The brain-path list Eternia reads: ONE file naming, for this machine, every brain (RT-BRAIN-PATHS-PLAIN-LIST).

Contract: ``EterniaLauncher/docs/mission_control/planned/THREE_BRAINS_ONE_READER_2026-11-02.md`` ("The one
list") and the shared w1102c contract; fixture ``tests/fixtures/brain_paths_v1.json`` (identical bytes in the
launcher's ``test/fixtures/mission_control/brain_paths_v1.json``). Hermes writes
``<namespace>/agent-runtime/brain_paths.json`` atomically; Eternia only reads it, so a to-do read needs no serve
call, no git and no booted runtime.

Three brains, one shape (``{path, brain_dir, behind}``):

* ``personal`` — the personal board's home (``work_store.board.PERSONAL_BOARD_ID``'s default brain,
  ``work/personal/brain``, which carries ``Work_Brain/``): null until it is created.
* ``workspaces.<id>.brain`` — the workspace's own brain, its default brain while that binding is live
  (``work_store.board.default_board``); null when it has none here.
* ``workspaces.<id>.projects[].slots[]`` — every live folder slot of every Project the workspace holds, in the
  workspace's ``project_ids`` order, slots in the order the store records them (by name). ``path`` is this
  machine's fill (null: not bound here); ``brain_dir`` comes from :func:`work_store.board.brain_dir_of` — the
  declared ``context.brain_dir``, else the work store's own detection — as the brain FOLDER (``Launcher_Brain``,
  the folder holding ``TODO.md`` and ``20 — Active Initiatives/``), null when there is none.

``brain_dir`` is relative to ``path``; ``behind`` is the upstream commit count the remote check
(:mod:`agent_runtime.brain_remote`) last measured, null when unmeasured or the brain has no upstream.

:func:`changed` is the one call every write chokepoint makes (workspaces, Projects, slot fills, slot
documents, default-brain bindings, brain creation, a realm pull) and the serve calls once at boot before any
heavy boot work. It never raises into its caller; an unchanged list is not rewritten (``written_at`` aside).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from utils import atomic_json_write

from . import paths

__layer__ = "stores"
__all__ = [
    "BRAIN_PATHS_FILENAME",
    "BRAIN_PATHS_SCHEMA_VERSION",
    "brain_folder",
    "brain_paths_path",
    "brains",
    "build_brain_paths",
    "changed",
    "held_counts",
    "read_brain_paths",
    "write_brain_paths",
]

logger = logging.getLogger(__name__)

BRAIN_PATHS_FILENAME = "brain_paths.json"
BRAIN_PATHS_SCHEMA_VERSION = 1
#: The queue folder under a brain (``work_store.board._BRAIN_GLOBS``' tail).
QUEUE_FOLDER = "20 — Active Initiatives"

_lock = threading.RLock()
_local = threading.local()


def brain_paths_path() -> Path:
    return paths.store_root() / BRAIN_PATHS_FILENAME


def brain_folder(root: Path | None, queue_dir: str | None) -> str | None:
    """The brain FOLDER (``Launcher_Brain``) for the work store's queue dir (``Launcher_Brain/20 — …``), when it
    exists under ``root``; None when ``root`` or the brain is not here."""

    if root is None or not queue_dir or not (root / queue_dir).is_dir():
        return None
    brain = PurePosixPath(queue_dir)
    folder = brain.parent if brain.name == QUEUE_FOLDER and str(brain.parent) != "." else brain
    return folder.as_posix()


def _brain(path: Path | None, queue_dir: str | None, behind: Mapping[str, int | None]) -> dict[str, Any]:
    here = path if path is not None and path.is_dir() else None
    folder = brain_folder(here, queue_dir)
    text = str(here) if here is not None else None
    return {"path": text, "brain_dir": folder, "behind": behind.get(text) if text and folder else None}


def _default_brain(owner: str, behind: Mapping[str, int | None]) -> dict[str, Any]:
    from .work_store.board import default_board

    board = default_board(owner)
    if board is None:
        return _brain(None, None, behind)
    root = board.checkout
    if board.local:
        from .work_store.writer import Writer

        # Local brains have no upstream to pull. Accepted writes live in the
        # native writer's worktree; the seed checkout is only the initial view.
        worktree = Writer(board, machine_id="brain-paths").worktree
        if (worktree / ".git").exists():
            root = worktree
    return _brain(root, board.brain_dir, behind)


def _project(project_id: str, behind: Mapping[str, int | None]) -> dict[str, Any]:
    from .project_store import load_project
    from .work_store.board import brain_dir_of
    from .workspace_slots import bound_path, live_slots

    record = load_project(project_id)
    slots = []
    for name, declaration in sorted(live_slots(record).items()):
        path = bound_path(name, project_id=project_id)
        here = path if path is not None and path.is_dir() else None
        slots.append({"slot": name, **_brain(here, brain_dir_of(here, declaration) if here else None, behind)})
    return {"project_id": project_id, "name": str(record.get("name") or "").strip() or project_id, "slots": slots}


def build_brain_paths(*, behind: Mapping[str, int | None] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """The list as it stands on this machine now. ``behind`` maps a brain's ``path`` to its upstream count."""

    from .store import WorkspaceStore
    from .work_store.board import PERSONAL_BOARD_ID

    counts = dict(behind or {})
    workspaces: dict[str, Any] = {}
    for workspace in WorkspaceStore().list_all():
        workspaces[workspace.id] = {
            "name": workspace.name,
            "brain": _default_brain(workspace.id, counts),
            "projects": [_project(project_id, counts) for project_id in workspace.project_ids],
        }
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"schema_version": BRAIN_PATHS_SCHEMA_VERSION, "written_at": stamp,
            "personal": _default_brain(PERSONAL_BOARD_ID, counts), "workspaces": workspaces}


def read_brain_paths() -> dict[str, Any] | None:
    try:
        payload = json.loads(brain_paths_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def brains(payload: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    """``(kind, entry)`` for every brain in a list: ``personal`` / ``workspace`` / ``project``."""

    if not payload:
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(payload.get("personal"), dict):
        out.append(("personal", payload["personal"]))
    for workspace in (payload.get("workspaces") or {}).values():
        if isinstance(workspace.get("brain"), dict):
            out.append(("workspace", workspace["brain"]))
        for project in workspace.get("projects") or []:
            out.extend(("project", slot) for slot in project.get("slots") or [])
    return out


def held_counts() -> dict[str, int | None]:
    return {str(entry["path"]): entry.get("behind") for _kind, entry in brains(read_brain_paths())
            if entry.get("path") and entry.get("behind") is not None}


def _body(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (payload or {}).items() if key != "written_at"}


def write_brain_paths(*, behind: Mapping[str, int | None] | None = None, now: datetime | None = None) -> bool:
    """Build and write the list atomically; True when the file changed. ``behind=None`` keeps the counts held."""

    with _lock:
        payload = build_brain_paths(behind=held_counts() if behind is None else behind, now=now)
        if _body(payload) == _body(read_brain_paths()):
            return False
        target = brain_paths_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(target, payload, indent=2)
        return True


def changed(reason: str) -> bool:
    """A chokepoint changed a workspace, Project, slot, binding or brain: rewrite the list. Never raises.

    Re-entrant calls (a read inside the build that upgrades a legacy registry and writes it) are dropped: the
    outer build reads the upgraded state.
    """

    if getattr(_local, "active", False):
        return False
    _local.active = True
    try:
        return write_brain_paths()
    except Exception:
        logger.warning("brain_paths rewrite after %s failed", reason, exc_info=True)
        return False
    finally:
        _local.active = False
