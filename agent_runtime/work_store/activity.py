"""A workspace's task activity, kept as a sidecar the snapshot reads (RT-WORKSPACE-SUMMARY-ACTIVITY).

``workspace_summary`` carries ``tasks_running``, ``needs_you`` and ``last_activity_at`` for every workspace
card, and the snapshot path may not walk a board's notes or call git to get them. So the Work engine — which
already syncs and reads every workspace's boards on each tick (``WorkEngine._start_claimed``) — hands what it
read to :func:`record_view`, which keeps ``<work>/<workspace>/activity.json``; the snapshot reads that one small
file through :func:`read_activity` (the pattern of the realm sync sidecar). One writer, one reader.

The counts follow the launcher's one column rule (``workBoardColumnOf``), over TASKS — a ``task:`` row, or a row
no task on these boards owns (a subtask counts through its task):

* ``tasks_running`` — tasks carrying a claim (``TAKEN``): a persona or a session lane is working it;
* ``needs_you`` — unclaimed tasks that wait on the owner (``DECISION``, or ``BLOCKED`` on an owner reason);
* ``last_activity_at`` — the newer of the newest commit that changed a board's queue notes (the last time a
  task here was created, claimed, moved or closed) and the last chat turn held in the workspace (ISO-8601 UTC).

The two counts are ``None`` until the engine has read every board of the workspace on this machine whole — a
board with no worktree here, or one whose sync refused, is "not known", never a zero. A workspace with no
board has no tasks: both counts are 0.

Chat recency (RT-WORKSPACE-LAST-ACTIVITY-COUNTS-CHATS) is a second small file with its own one writer,
``<work>/<workspace>/chat_activity.json``: the chat turn's commit stamps it at turn end
(:func:`record_chat_turn`, called from ``workspace_chat_export.export_after_turn``) for the workspace the
turn's persona instance is placed in and every workspace the session is shared into. A turn of an instance
placed in no workspace stamps nothing. It appends no event: like a moved task time, it rides the next build.

Pinned by ``tests/agent_runtime/work_store/test_activity.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..events import EventLog
from ..serde import read_json, write_json_atomic
from ..store_events import emit_store_event
from .grammar import Row
from .tasks import owning_task, waits_on_owner

__layer__ = "stores"
__all__ = ["ACTIVITY_FIELDS", "count_tasks", "read_activity", "record_chat_turn", "record_view"]

logger = logging.getLogger(__name__)

#: The three keys ``workspace_summary`` carries, in wire order.
ACTIVITY_FIELDS = ("tasks_running", "needs_you", "last_activity_at")
_COUNTS = ACTIVITY_FIELDS[:2]
_UNKNOWN: dict[str, Any] = dict.fromkeys(ACTIVITY_FIELDS)


def _path(workspace_id: str) -> Path:
    return paths.work_workspace_dir(workspace_id) / "activity.json"


def count_tasks(rows: Iterable[Row]) -> dict[str, int]:
    """``{tasks_running, needs_you}`` over the tasks among ``rows`` (the module docstring's rule)."""

    rows = list(rows)
    slugs = {row.task for row in rows if row.task is not None}
    tasks = [row for row in rows
             if row.task is not None or row.group is None or owning_task(row.group, slugs) is None]
    return {"tasks_running": sum(1 for row in tasks if row.taken is not None),
            "needs_you": sum(1 for row in tasks if row.taken is None and waits_on_owner(row))}


def _chat_path(workspace_id: str) -> Path:
    return paths.work_workspace_dir(workspace_id) / "chat_activity.json"


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def record_chat_turn(workspace_ids: Iterable[str | None], *, when: datetime | None = None) -> list[str]:
    """Stamp a chat turn's end on each workspace it was held in; returns the workspaces stamped. Best effort
    per workspace (a failed stamp is logged, never raised into the turn)."""

    stamp = _stamp(when or datetime.now(UTC))
    done: list[str] = []
    for workspace_id in dict.fromkeys(item for item in workspace_ids if isinstance(item, str) and item):
        try:
            write_json_atomic(_chat_path(workspace_id), {"last_chat_at": stamp})
            done.append(workspace_id)
        except Exception:
            logger.warning("could not stamp chat activity on workspace %s", workspace_id, exc_info=True)
    return done


def _last_chat_at(workspace_id: str) -> str | None:
    try:
        stamp = read_json(_chat_path(workspace_id)).get("last_chat_at")
    except Exception:
        return None
    return stamp if isinstance(stamp, str) else None


def _tasks(workspace_id: str) -> dict[str, Any]:
    """The engine's sidecar as stored (``last_activity_at`` there is the TASK time only)."""

    try:
        raw = read_json(_path(workspace_id))
    except Exception:
        return dict(_UNKNOWN)
    if not isinstance(raw, dict) or not all(isinstance(raw.get(key), int) for key in _COUNTS):
        return dict(_UNKNOWN)
    stamp = raw.get("last_activity_at")
    return {**{key: raw[key] for key in _COUNTS}, "last_activity_at": stamp if isinstance(stamp, str) else None}


def read_activity(workspace_id: str) -> dict[str, Any]:
    """The three fields ``workspace_summary`` carries: the engine's counts, and the newer of the task time
    and the last chat turn. Two small file reads, no board walk, no git — the snapshot path's read."""

    fields = _tasks(workspace_id)
    # Both stamps are second-resolution UTC ``…Z`` strings, so the newer one is the greater string.
    fields["last_activity_at"] = max(filter(None, (fields["last_activity_at"], _last_chat_at(workspace_id))),
                                     default=None)
    return fields


def _committed_at(view: Any) -> str | None:
    """The newest commit time over the view's boards' brain folders, as ISO ``Z``; None when no writer answers."""

    times: list[int] = []
    for board in view.boards:
        writer = view.writers.get(board.key)
        brain = getattr(board, "brain_dir", None)
        if writer is None or not brain:
            continue
        try:
            when = writer.note_committed_at(brain)
        except Exception:
            when = None
        if isinstance(when, (int, float)):
            times.append(int(when))
    if not times:
        return None
    return _stamp(datetime.fromtimestamp(max(times), UTC))


def record_view(workspace_id: str, view: Any, read: Mapping[str, list[Row]],
                *, event_log: EventLog | None = None) -> bool:
    """Keep the sidecar from one engine read of the workspace: ``view`` (``work.store.Synced``) and ``read``,
    the rows of each board the engine read, keyed by board key. Returns whether the file was written.

    Nothing is recorded unless EVERY board of the view was read (a refused or worktree-less board would make
    the counts a partial truth). The file is written only when a field changed, and ``workspace.updated``
    (``change: task_activity``) is appended only when a COUNT changed — a moved ``last_activity_at`` rides the
    next snapshot build instead of forcing one per commit.
    """

    boards = list(view.boards)
    if getattr(view, "refused", None) or any(board.key not in read for board in boards):
        return False
    fresh: dict[str, Any] = count_tasks(row for board in boards for row in read[board.key])
    before = _tasks(workspace_id)
    fresh["last_activity_at"] = _committed_at(view) or before["last_activity_at"]
    if fresh == before:
        return False
    write_json_atomic(_path(workspace_id), fresh)
    if any(fresh[key] != before[key] for key in _COUNTS):
        emit_store_event(event_log or EventLog(), "workspace.updated",
                         {"workspace_id": workspace_id, "change": "task_activity"}, domain="store")
    return True
