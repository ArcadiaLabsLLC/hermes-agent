"""Undo an action Lens took (row ``RT-LENS-UNDO-ACTION``, design ``planned/lens-act-and-safe-investigate.md``
§4: "the receipt carries the undo handle").

A file write an ``act`` turn is allowed to make is undoable only when Lens holds its BEFORE image: the gate
(``act.ActTurn.decide``) reads the target file before the call runs (:func:`capture`) — the bytes, or that
it did not exist — and the receipt's ``undo_handle`` names it (``{kind: file, path, existed}``). A write
whose before image cannot be read (no ``path`` argument, as ``apply_patch``; a container or remote path; a
file over :data:`MAXIMUM_UNDO_BYTES`; a directory) is "cannot be undone", so it goes to the owner as a
proposal.

Why Lens keeps its own image and not the turn's checkpoints (``operator_undo.py``), as the design first
said — read in code 2026-11-14: the runtime checkpoints a write only for a top-level ``write_file`` /
``patch`` and only when the agent's checkpoint manager is enabled (``agent/tool_executor.py``), while a
Lens turn's file tools are deferred and reach the gate through the ``tool_call`` bridge, which is never
checkpointed. An image Lens takes itself exists for every call it lets run.

Realm writes: no tool in the mutating set (``read_only``'s block list) writes a realm, so none can be an
act action today; one added later is not in :data:`act.UNDOABLE_TOOLS` and so stays "cannot be undone".

:func:`undo` restores the image (writes the bytes back, or removes a file the action created), writes an
undo receipt (``tool: undo``, ``decided_by: owner``, ``result: ran | failed``) and marks the action
``undone_by`` it. ``runtime.lens.undo {action_id}`` is its door.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .store import LensStore, LensStoreError, StoreRefusal
from .store_actions import ActionResult, action, record_action, set_undone_by

__layer__ = "stores"

logger = logging.getLogger(__name__)

#: A file larger than this is not imaged, so a write to it cannot be undone (it goes to the owner).
MAXIMUM_UNDO_BYTES = 1024 * 1024
UNDO_TOOL = "undo"
WHY_UNDO = "undo"

_TABLES = """
CREATE TABLE IF NOT EXISTS lens_action_undo (
  action_id TEXT PRIMARY KEY, path TEXT NOT NULL, existed INTEGER NOT NULL, content BLOB);
"""


class BeforeImage:
    """A file's state before an action wrote it."""

    def __init__(self, path: str, existed: bool, content: bytes | None) -> None:
        self.path, self.existed, self.content = path, existed, content

    def handle(self) -> dict[str, Any]:
        return {"kind": "file", "path": self.path, "existed": self.existed}


def add_undo_tables(conn: Any) -> None:
    conn.executescript(_TABLES)


def capture(arguments: Any, task_id: str | None) -> BeforeImage | None:
    """The target file's before image, or None when it cannot be taken (the write cannot be undone)."""

    raw = arguments.get("path") if isinstance(arguments, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        from tools.file_tools_paths import _resolve_path_for_task

        path = _resolve_path_for_task(raw, task_id or "default")
        if not isinstance(path, Path):  # a container or remote path: not on this host
            return None
        if not path.exists():
            return BeforeImage(str(path), False, None)
        if not path.is_file() or path.stat().st_size > MAXIMUM_UNDO_BYTES:
            return None
        return BeforeImage(str(path), True, path.read_bytes())
    except Exception:  # an image that cannot be read means no undo, never a guess
        logger.debug("lens undo: no before image for %r", raw, exc_info=True)
        return None


def keep_image(store: LensStore, action_id: str, image: BeforeImage) -> None:
    with store.connection() as conn:
        conn.execute("INSERT OR REPLACE INTO lens_action_undo (action_id, path, existed, content) VALUES (?, ?, ?, ?)",
                     (action_id, image.path, 1 if image.existed else 0, image.content))


def undo(store: LensStore, action_id: str, *, now_ms: int) -> dict[str, Any]:
    """Restore ``action_id``'s before image once; ``{action, receipt}``."""

    found = action(store, action_id)
    if found is None:
        raise LensStoreError(StoreRefusal.ACTION_NOT_FOUND)
    if found.get("undone_by"):
        raise LensStoreError(StoreRefusal.ACTION_ALREADY_UNDONE)
    with store.connection() as conn:
        image = conn.execute("SELECT path, existed, content FROM lens_action_undo WHERE action_id = ?",
                             (action_id,)).fetchone()
    if image is None or found["result"] != ActionResult.RAN:
        raise LensStoreError(StoreRefusal.ACTION_CANNOT_BE_UNDONE)
    path, existed, content = Path(image[0]), bool(image[1]), image[2]
    try:
        if existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.lens-undo")
            tmp.write_bytes(content or b"")
            os.replace(tmp, path)
        elif path.exists():
            path.unlink()
        result = ActionResult.RAN
    except OSError:
        logger.warning("lens undo of %s failed", action_id, exc_info=True)
        result = ActionResult.FAILED
    receipt = record_action(store, episode_id=found["episode_id"], monitor_id=found["monitor_id"],
                            turn_id=found["turn_id"], tool=UNDO_TOOL, arguments={"action_id": action_id},
                            verdict=None, decided_by="owner", result=result, why=WHY_UNDO, undoable=False,
                            created_ms=now_ms)
    if result == ActionResult.RAN:
        set_undone_by(store, action_id, receipt["action_id"])
    return {"action": action(store, action_id), "receipt": receipt}
