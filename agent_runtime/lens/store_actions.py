"""Lens ACTION receipts: one row per mutating tool call an ``act`` turn tried (design
``planned/lens-act-and-safe-investigate.md`` §4, row ``RT-LENS-ACT-LEVEL``).

A row is ``{action_id, episode_id, monitor_id, turn_id, tool, arguments_digest, verdict, decided_by,
result, why, undoable, undo_handle, arguments, created_ms, finished_ms}``:

* ``verdict`` — the rules check's ``approve | deny | escalate``, or null when no check ran (the call
  went straight to the owner: not listed, cannot be undone, or untrusted free text in the Episode);
* ``decided_by`` — ``rules`` when the check decided it; ``owner`` for a proposal (the owner answers it);
* ``result`` — ``running`` (allowed, the tool is executing), ``ran``, ``failed``, ``refused`` (the rules
  denied it; the model was told) or ``proposed`` (sent to the owner; the turn carried on without it);
* ``arguments`` — kept only on a proposal (the owner reads what they would approve), at most
  :data:`MAXIMUM_PROPOSAL_ARGUMENT_BYTES`, else null; every row keeps the digest;
* ``undo_handle`` — null until ``RT-LENS-UNDO-ACTION`` records one.

Named apart from ``store_proposals.py`` (the money ``best_of`` proposal evidence), which this is not.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from typing import Any

from .store import LensStore
from .wire_value import canonical_digest

__layer__ = "stores"

#: A proposal's stored arguments; past it only the digest is kept.
MAXIMUM_PROPOSAL_ARGUMENT_BYTES = 64 * 1024
MAXIMUM_ACTIONS_PAGE = 256

_TABLES = """
CREATE TABLE IF NOT EXISTS lens_actions (
  action_id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, monitor_id TEXT NOT NULL, turn_id TEXT NOT NULL,
  tool_call_id TEXT, tool TEXT NOT NULL, arguments_digest TEXT NOT NULL, arguments TEXT, verdict TEXT,
  decided_by TEXT, result TEXT NOT NULL, why TEXT, undoable INTEGER NOT NULL, undo_handle TEXT,
  created_ms INTEGER NOT NULL, finished_ms INTEGER);
CREATE INDEX IF NOT EXISTS lens_actions_by_episode ON lens_actions (episode_id, created_ms);
CREATE INDEX IF NOT EXISTS lens_actions_by_monitor ON lens_actions (monitor_id, created_ms);
"""
_COLUMNS = ("action_id", "episode_id", "monitor_id", "turn_id", "tool_call_id", "tool", "arguments_digest",
            "arguments", "verdict", "decided_by", "result", "why", "undoable", "undo_handle", "created_ms",
            "finished_ms")


class ActionResult:
    RUNNING = "running"
    RAN = "ran"
    FAILED = "failed"
    REFUSED = "refused"
    PROPOSED = "proposed"


def add_action_tables(conn: sqlite3.Connection) -> None:
    """The action-receipt table, on every store open (``LensStore._db``)."""

    conn.executescript(_TABLES)


def arguments_digest(arguments: Any) -> str:
    try:
        return canonical_digest(arguments)
    except Exception:  # a value canonical JSON refuses (a float NaN, an object): digest its plain JSON
        import hashlib

        return hashlib.sha256(json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()


def record_action(store: LensStore, *, episode_id: str, monitor_id: str, turn_id: str, tool: str, arguments: Any,
                  verdict: str | None, decided_by: str | None, result: str, why: str | None, undoable: bool,
                  created_ms: int, tool_call_id: str | None = None) -> dict[str, Any]:
    kept = None
    if result == ActionResult.PROPOSED:
        text = json.dumps(arguments, sort_keys=True, default=str)
        kept = text if len(text.encode("utf-8")) <= MAXIMUM_PROPOSAL_ARGUMENT_BYTES else None
    settled = result != ActionResult.RUNNING
    row = (f"lens-action-{secrets.token_hex(8)}", episode_id, monitor_id, turn_id, tool_call_id, tool,
           arguments_digest(arguments), kept, verdict, decided_by, result, why, 1 if undoable else 0, None,
           int(created_ms), int(created_ms) if settled else None)
    with store.connection() as conn:
        conn.execute(f"INSERT INTO lens_actions ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
                     row)
    return _json(row)


def finish_action(store: LensStore, action_id: str, *, result: str, finished_ms: int) -> None:
    """A running (allowed) call's end: ``ran`` or ``failed``."""

    with store.connection() as conn:
        conn.execute("UPDATE lens_actions SET result = ?, finished_ms = ? WHERE action_id = ? AND result = ?",
                     (result, int(finished_ms), action_id, ActionResult.RUNNING))


def actions(store: LensStore, *, episode_id: str | None = None, monitor_id: str | None = None,
            limit: int = 32) -> list[dict[str, Any]]:
    """Newest first, for one Episode, one monitor, or all."""

    if not store.exists():
        return []
    where, params = [], []
    for column, value in (("episode_id", episode_id), ("monitor_id", monitor_id)):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with store.connection() as conn:
        rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM lens_actions{clause} "
                            "ORDER BY created_ms DESC, rowid DESC LIMIT ?", (*params, int(limit))).fetchall()
    return [_json(row) for row in rows]


def _json(row: tuple[Any, ...]) -> dict[str, Any]:
    out = dict(zip(_COLUMNS, row))
    out["undoable"] = bool(out["undoable"])
    out["arguments"] = None if out["arguments"] is None else json.loads(out["arguments"])
    out.pop("tool_call_id")
    return out
