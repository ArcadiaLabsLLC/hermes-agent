"""Lens workspace scope and ORPHANED Episodes (row ``RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS``).

One store per runtime (``store.lens_root()``) holds every workspace's monitors, so a monitor
records the workspace it was created in (``monitors.workspace_id``; NULL for a monitor written
before the column, which only the all-workspaces read shows). Its Episodes and receipts carry
that workspace on every served row (:func:`with_scope`), read through the monitor they belong
to — never a second copy that could disagree. A ``runtime.lens.*`` read given ``workspace_id``
answers only that workspace; without it, every workspace (the answer it always gave).

An open Episode (``active`` / ``recovered``) whose monitor no longer observes it is ORPHANED:
nothing will ever move it again, so it would stay open forever — the five the owner's panel
showed on 2026-11-08, left by a live-proof sitting that paused and retired its monitors with
their Episodes still ``active``. :func:`orphan_reason` names why (:class:`Orphan`), every
served row says so (``orphan``: the reason, or None), and :func:`close_orphans` settles them
in one call as ``resolved``: the operator's word on a breach that can no longer be watched.
Retiring a monitor closes its open Episodes at once (``LensStore.set_state``), and a
``dismiss`` of an orphan closes it (``store_decisions.decide_episode``), so Dismiss is never
recorded on an Episode that then stays open.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from enum import Enum
from typing import Any, Iterable

from .episode import Decision, Episode, EpisodeState
from .store import LensStore, MonitorState

__layer__ = "stores"

#: The states an Episode is open in, and so can be orphaned.
_OPEN = (EpisodeState.ACTIVE.value, EpisodeState.RECOVERED.value)


class Orphan(str, Enum):
    """Why an open Episode's monitor will never observe it again."""

    MONITOR_GONE = "monitor_gone"
    MONITOR_RETIRED = "monitor_retired"
    #: Paused: nothing polls it until the operator enables it again (closing it then is safe:
    #: the next breach opens the next ordinal).
    MONITOR_PAUSED = "monitor_paused"


_BY_STATE = {MonitorState.RETIRED.value: Orphan.MONITOR_RETIRED, MonitorState.PAUSED.value: Orphan.MONITOR_PAUSED}


def add_workspace_column(conn: sqlite3.Connection) -> None:
    """A store written before workspace scope gains ``monitors.workspace_id``; its monitors read NULL."""

    if "workspace_id" not in {row[1] for row in conn.execute("PRAGMA table_info(monitors)")}:
        conn.execute("ALTER TABLE monitors ADD COLUMN workspace_id TEXT")


def active_workspace_id() -> str | None:
    """The runtime's active workspace, the one a create without ``workspace_id`` belongs to.
    None when none is active or the pointer is unreadable (the monitor is then unscoped)."""

    try:
        from ..store import WorkspaceStore

        return WorkspaceStore().active_id() or None
    except Exception:
        return None


def workspace_param(params: dict | None) -> str | None:
    """The read's ``workspace_id`` (an opaque id), or None for every workspace."""

    from .wire_value import opaque_id

    value = (params or {}).get("workspace_id")
    return None if value is None else opaque_id(value)


def _monitors(store: LensStore) -> dict[str, tuple[str, str | None]]:
    """``monitor_id -> (state, workspace_id)`` for every stored monitor."""

    if not store.exists():
        return {}
    with store.connection() as conn:
        rows = conn.execute("SELECT monitor_id, state, workspace_id FROM monitors").fetchall()
    return {monitor_id: (state, workspace) for monitor_id, state, workspace in rows}


def orphan_reason(monitors: dict[str, tuple[str, str | None]], episode: dict[str, Any]) -> str | None:
    """Why this open Episode is orphaned, or None (settled, or its monitor still observes it)."""

    if episode.get("state") not in _OPEN:
        return None
    known = monitors.get(episode.get("monitor_id"))
    if known is None:
        return Orphan.MONITOR_GONE.value
    reason = _BY_STATE.get(known[0])
    return None if reason is None else reason.value


def with_scope(store: LensStore, rows: Iterable[dict[str, Any]], *, workspace_id: str | None = None,
               episodes: bool = True) -> list[dict[str, Any]]:
    """Each row with its monitor's ``workspace_id`` (and, for Episodes, ``orphan``), kept only
    when ``workspace_id`` is None or names that row's workspace."""

    monitors = _monitors(store)
    out = []
    for row in rows:
        workspace = (monitors.get(row.get("monitor_id")) or (None, None))[1]
        if workspace_id is not None and workspace != workspace_id:
            continue
        scoped = {**row, "workspace_id": workspace}
        if episodes:
            scoped["orphan"] = orphan_reason(monitors, row)
        out.append(scoped)
    return out


def workspace_monitor_ids(store: LensStore, workspace_id: str | None) -> set[str] | None:
    """The monitors of ``workspace_id``; None (no filter) when it is None."""

    if workspace_id is None:
        return None
    return {monitor_id for monitor_id, (_, workspace) in _monitors(store).items() if workspace == workspace_id}


def is_orphaned(store: LensStore, episode: Episode) -> bool:
    return orphan_reason(_monitors(store), episode.to_json()) is not None


def resolved(episode: Episode, now: datetime) -> Episode:
    """The orphan settled: ``resolved``, with the operator's dismissal when nothing was decided."""

    if episode.decision is not None:
        return replace(episode, state=EpisodeState.RESOLVED)
    return replace(episode, state=EpisodeState.RESOLVED, decision=Decision.DISMISS,
                   decided_at=max(now, episode.first_seen))


def close_orphans(store: LensStore, now: datetime, *, workspace_id: str | None = None,
                  monitor_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Resolve every orphaned open Episode (of ``workspace_id`` / ``monitor_ids`` when given);
    returns the closed Episodes as stored. A row another writer moved first is left for the
    next call, never overwritten."""

    if not store.exists():
        return []
    monitors = _monitors(store)
    only = None if monitor_ids is None else set(monitor_ids)
    marks = ",".join("?" * len(_OPEN))
    with store.connection() as conn:
        bodies = [json.loads(row[0]) for row in conn.execute(
            f"SELECT body FROM episodes WHERE state IN ({marks}) ORDER BY monitor_id, rule_id, ordinal", _OPEN)]
    closed = []
    for body in bodies:
        if only is not None and body["monitor_id"] not in only:
            continue
        if workspace_id is not None and (monitors.get(body["monitor_id"]) or (None, None))[1] != workspace_id:
            continue
        if orphan_reason(monitors, body) is None:
            continue
        episode = Episode.from_json(body)
        settled = resolved(episode, now)
        if store.move_episode(episode, settled, announce=True):
            closed.append(settled.to_json())
    return closed
