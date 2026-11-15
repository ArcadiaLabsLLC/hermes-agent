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
* ``undo_handle`` — null until ``RT-LENS-UNDO-ACTION`` records one;
* a proposal's answer (row ``RT-LENS-PROPOSAL-APPROVE-DENY``, design §4, decision 5): ``result`` moves
  ``proposed`` -> ``approved`` | ``denied`` (the owner, ``answered_ms``) or ``expired`` (unanswered for
  :data:`PROPOSAL_TTL_MS`); ``expires_ms`` says when. An approval owes ONE follow-up turn in the Episode's
  chat with that call pre-admitted; ``follow_up_turn_id`` is set when the door claims it (once).

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
#: An unanswered proposal expires a day after it was made (owner decision 5: a stale "bid now" is worse).
PROPOSAL_TTL_MS = 24 * 60 * 60 * 1000

_TABLES = """
CREATE TABLE IF NOT EXISTS lens_actions (
  action_id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, monitor_id TEXT NOT NULL, turn_id TEXT NOT NULL,
  tool_call_id TEXT, tool TEXT NOT NULL, arguments_digest TEXT NOT NULL, arguments TEXT, verdict TEXT,
  decided_by TEXT, result TEXT NOT NULL, why TEXT, undoable INTEGER NOT NULL, undo_handle TEXT,
  created_ms INTEGER NOT NULL, finished_ms INTEGER, answered_ms INTEGER, follow_up_turn_id TEXT);
CREATE INDEX IF NOT EXISTS lens_actions_by_episode ON lens_actions (episode_id, created_ms);
CREATE INDEX IF NOT EXISTS lens_actions_by_monitor ON lens_actions (monitor_id, created_ms);
"""
_COLUMNS = ("action_id", "episode_id", "monitor_id", "turn_id", "tool_call_id", "tool", "arguments_digest",
            "arguments", "verdict", "decided_by", "result", "why", "undoable", "undo_handle", "created_ms",
            "finished_ms", "answered_ms", "follow_up_turn_id")


class ActionResult:
    RUNNING = "running"
    RAN = "ran"
    FAILED = "failed"
    REFUSED = "refused"
    PROPOSED = "proposed"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


#: The results a proposal row moves through (every other row is an action the turn took or was refused).
PROPOSAL_RESULTS = frozenset({ActionResult.PROPOSED, ActionResult.APPROVED, ActionResult.DENIED,
                              ActionResult.EXPIRED})


def add_action_tables(conn: sqlite3.Connection) -> None:
    """The action-receipt table, on every store open (``LensStore._db``)."""

    conn.executescript(_TABLES)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(lens_actions)")}
    for column, kind in (("answered_ms", "INTEGER"), ("follow_up_turn_id", "TEXT")):  # a store from before answers
        if column not in columns:
            conn.execute(f"ALTER TABLE lens_actions ADD COLUMN {column} {kind}")


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
           int(created_ms), int(created_ms) if settled else None, None, None)
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


def action(store: LensStore, action_id: str) -> dict[str, Any] | None:
    if not store.exists():
        return None
    with store.connection() as conn:
        row = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM lens_actions WHERE action_id = ?",
                           (action_id,)).fetchone()
    return None if row is None else _json(row)


def wall_ms() -> int:
    """Now, for the owner's answer (``runtime.lens.proposal.answer``); a seam tests move."""

    from datetime import UTC, datetime

    from .store import to_ms

    return to_ms(datetime.now(UTC))


def answer_proposal(store: LensStore, action_id: str, *, approve: bool, now_ms: int) -> dict[str, Any]:
    """The owner's answer: ``approved`` or ``denied``, once, while the proposal is open."""

    from .store import LensStoreError, StoreRefusal

    found = action(store, action_id)
    if found is None or found["result"] not in PROPOSAL_RESULTS:
        raise LensStoreError(StoreRefusal.PROPOSAL_NOT_FOUND)
    if found["result"] != ActionResult.PROPOSED or now_ms >= found["created_ms"] + PROPOSAL_TTL_MS:
        raise LensStoreError(StoreRefusal.PROPOSAL_SETTLED)
    result = ActionResult.APPROVED if approve else ActionResult.DENIED
    with store.connection() as conn:
        changed = conn.execute("UPDATE lens_actions SET result = ?, answered_ms = ?, finished_ms = ? "
                               "WHERE action_id = ? AND result = ?",
                               (result, int(now_ms), int(now_ms), action_id, ActionResult.PROPOSED)).rowcount
    if not changed:
        raise LensStoreError(StoreRefusal.PROPOSAL_SETTLED)
    return action(store, action_id)


def expire_proposals(store: LensStore, now_ms: int) -> int:
    """Every proposal unanswered for :data:`PROPOSAL_TTL_MS` becomes ``expired``; how many did."""

    if not store.exists():
        return 0
    with store.connection() as conn:
        return conn.execute("UPDATE lens_actions SET result = ?, finished_ms = ? WHERE result = ? AND created_ms <= ?",
                            (ActionResult.EXPIRED, int(now_ms), ActionResult.PROPOSED,
                             int(now_ms) - PROPOSAL_TTL_MS)).rowcount


def follow_up_turn_id(episode_id: str, action_id: str) -> str:
    """The follow-up turn's client message id: the Episode's own, plus the approved proposal."""

    from .provenance import lens_client_message_id

    return f"{lens_client_message_id(episode_id)}:approved:{action_id}"


def claim_follow_ups(store: LensStore) -> list[dict[str, Any]]:
    """The approved proposals still owed their follow-up turn, each claimed once (``follow_up_turn_id``)."""

    if not store.exists():
        return []
    claimed = []
    with store.connection() as conn:
        ids = conn.execute("SELECT action_id, episode_id FROM lens_actions WHERE result = ? AND "
                           "follow_up_turn_id IS NULL ORDER BY answered_ms", (ActionResult.APPROVED,)).fetchall()
        for action_id, episode_id in ids:
            turn_id = follow_up_turn_id(episode_id, action_id)
            if conn.execute("UPDATE lens_actions SET follow_up_turn_id = ? WHERE action_id = ? AND "
                            "follow_up_turn_id IS NULL", (turn_id, action_id)).rowcount:
                claimed.append(action_id)
    return [row for row in (action(store, action_id) for action_id in claimed) if row is not None]


def _json(row: tuple[Any, ...]) -> dict[str, Any]:
    out = dict(zip(_COLUMNS, row))
    out["undoable"] = bool(out["undoable"])
    out["expires_ms"] = (out["created_ms"] + PROPOSAL_TTL_MS) if out["result"] == ActionResult.PROPOSED else None
    out["arguments"] = None if out["arguments"] is None else json.loads(out["arguments"])
    out.pop("tool_call_id")
    return out
