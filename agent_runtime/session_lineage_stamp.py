"""A cheap "has this chat's native history changed?" stamp over SessionDB.

A free function over upstream's ``SessionDB`` (its ``_read_ctx``, ``_execute_write``
and ``_resume_lineage_ids``), not a mixin: ``hermes_state.py`` stays stock.

The stamp is a fork-owned table, ``fork_session_revision``, bumped by SQLite
triggers on every ``messages`` INSERT, UPDATE and DELETE. Messages are updated in
place (transcript repair, ``active``/``compacted`` flips, display-order upkeep), so
"max row id + count" is not a sound revision; a trigger sees every writer, upstream
or fork, without a line of upstream code. Plan:
``docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md`` (S1).

The schema installs lazily on the first stamp, not on connect. That is sound
because stamps are only ever compared with stamps: the first one is taken after
the triggers exist, so every later write bumps something it covers. If the
triggers or the table go missing (a table rebuild drops triggers; a regenerated
database drops the table), the next stamp reinstalls them under a NEW epoch, so no
stamp taken before the gap can ever equal one taken after it.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from typing import Any, NamedTuple, Optional

__layer__ = "policy"

REVISION_TABLE = "fork_session_revision"
EPOCH_TABLE = "fork_session_revision_epoch"
TRIGGER_NAMES = (
    "fork_session_revision_insert",
    "fork_session_revision_update",
    "fork_session_revision_delete",
)

_BUMP = (
    f"INSERT INTO {REVISION_TABLE}(session_id, revision) VALUES ({{sid}}, 1) "
    "ON CONFLICT(session_id) DO UPDATE SET revision = revision + 1;"
)

#: Columns upstream derives from the others and maintains by itself (its display
#: triggers and repairs); see :data:`PAYLOAD_COLUMNS`.
DERIVED_COLUMNS = ("display_order", "display_identity", "message_uid")
#: Every other ``messages`` column. An UPDATE bumps unless it changed derived columns
#: only. A column upstream adds later still bumps when written alone; a gate
#: (``test_every_messages_column_is_classified``) reds until it is listed here.
PAYLOAD_COLUMNS = (
    "id", "session_id", "role", "content", "tool_call_id", "tool_calls", "tool_name",
    "effect_disposition", "timestamp", "token_count", "finish_reason", "reasoning",
    "reasoning_content", "reasoning_details", "codex_reasoning_items", "codex_message_items",
    "platform_message_id", "observed", "_compressed_summary", "active", "compacted",
    "api_content", "display_kind", "display_metadata", "absorbed_message_uids",
    "tool_call_uids", "tool_call_uid",
)
_UPDATE_BUMPS_WHEN = "(" + " AND ".join(
    f"new.{c} IS old.{c}" for c in DERIVED_COLUMNS) + ") OR " + " OR ".join(
    f"new.{c} IS NOT old.{c}" for c in PAYLOAD_COLUMNS)

_SCHEMA = (
    f"CREATE TABLE IF NOT EXISTS {REVISION_TABLE} ("
    "session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)",
    f"CREATE TABLE IF NOT EXISTS {EPOCH_TABLE} ("
    "singleton INTEGER PRIMARY KEY CHECK (singleton = 0), epoch TEXT NOT NULL)",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAMES[0]} AFTER INSERT ON messages BEGIN "
    + _BUMP.format(sid="new.session_id") + " END",
    # Both sides of an update: a row moved between sessions changes both. An update
    # that only re-derives display bookkeeping (upstream's own triggers and display
    # repairs, three to four per appended row) is skipped: that write cost is what
    # kept the stamp under its write budget (plan S1).
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAMES[1]} AFTER UPDATE ON messages WHEN "
    + _UPDATE_BUMPS_WHEN + " BEGIN "
    + _BUMP.format(sid="old.session_id")
    + f" UPDATE {REVISION_TABLE} SET revision = revision + 1 "
    "WHERE session_id = new.session_id AND new.session_id IS NOT old.session_id;"
    f" INSERT OR IGNORE INTO {REVISION_TABLE}(session_id, revision) VALUES (new.session_id, 1); END",
    f"CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAMES[2]} AFTER DELETE ON messages BEGIN "
    + _BUMP.format(sid="old.session_id") + " END",
)


class LineageStamp(NamedTuple):
    """Equal stamps mean no ``messages`` row of the lineage changed between them."""

    epoch: str
    tip: str
    sessions: tuple[str, ...]
    revisions: tuple[int, ...]


def _installed_epoch(conn) -> Optional[str]:
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name IN (?, ?, ?)", TRIGGER_NAMES)}
    if names != set(TRIGGER_NAMES):
        return None
    try:
        row = conn.execute(f"SELECT epoch FROM {EPOCH_TABLE} WHERE singleton = 0").fetchone()
    except sqlite3.OperationalError:  # no such table: not installed
        return None
    return row[0] if row else None


def ensure_installed(db: Any) -> Optional[str]:
    """Install the table and triggers if any part is missing; return the epoch (``None``: read-only store)."""
    with db._read_ctx() as conn:
        epoch = _installed_epoch(conn)
    if epoch is not None or getattr(db, "read_only", False):
        return epoch

    def _do(conn):
        current = _installed_epoch(conn)
        if current is not None:
            return current
        for statement in _SCHEMA:
            conn.execute(statement)
        fresh = secrets.token_hex(8)
        conn.execute(f"INSERT OR REPLACE INTO {EPOCH_TABLE}(singleton, epoch) VALUES (0, ?)", (fresh,))
        return fresh

    return db._execute_write(_do)


def lineage_stamp(db: Any, root_session_id: str) -> Optional[LineageStamp]:
    """The chat's native tip and the revision of every session of its compression lineage.

    ``None`` when the store cannot carry a stamp (read-only and not installed, or not a
    canonical SessionDB): the caller then reads as it always did.
    """
    from .chat_session_scope import is_canonical_session_persistence

    if (not is_canonical_session_persistence(db) or not callable(getattr(db, "_read_ctx", None))
            or not callable(getattr(db, "_resume_lineage_ids", None))):
        return None
    epoch = ensure_installed(db)
    if epoch is None:
        return None
    # Resolve the lineage FIRST and read revisions after it: a write that lands in
    # between bumps a revision this stamp then carries, never one it misses.
    tip = db.resolve_resume_session_id(root_session_id)
    sessions = tuple(db._resume_lineage_ids(tip))
    placeholders = ", ".join("?" for _ in sessions)
    with db._read_ctx() as conn:
        if _installed_epoch(conn) != epoch:
            return None
        found = dict(conn.execute(
            f"SELECT session_id, revision FROM {REVISION_TABLE} WHERE session_id IN ({placeholders})",
            sessions).fetchall())
    return LineageStamp(epoch, tip, sessions, tuple(int(found.get(s, 0)) for s in sessions))


#: A tool call id the JSON text of ``tool_calls`` spells byte-for-byte as itself,
#: whatever the writer's escaping; anything else takes the caller's full read.
_PLAIN_ID = re.compile(r"[A-Za-z0-9_.:\-]{1,200}")


def lineage_tool_rows(db: Any, root_session_id: str, *, tool_call_id: str, field: str) -> Optional[list[dict]]:
    """The lineage's DISPLAY rows that can carry ``tool_call_id``, decoded as the full display read decodes them.

    One query over the lineage's sessions, narrowed in SQLite to the rows that could
    match (``tool_result``: the tool rows answering that id; ``tool_input``: the
    assistant rows whose ``tool_calls`` text contains it), then deduped and decoded by
    SessionDB's own display functions. Every display-dedupe key of those rows carries
    the call id, so deduping the candidates alone picks the same representative the
    whole-lineage dedupe picks. The caller applies its usual matching, hidden-row
    filter and redaction — policy stays where it is. ``None``: use the full read.
    """
    if field not in ("tool_input", "tool_result") or not _PLAIN_ID.fullmatch(tool_call_id or ""):
        return None
    needed = ("_read_ctx", "_resume_lineage_ids", "_active_clause", "_dedupe_display_generations",
              "_row_to_message_dict", "resolve_resume_session_id")
    if not all(callable(getattr(db, name, None)) for name in needed):
        return None
    tip = db.resolve_resume_session_id(root_session_id)
    sessions = list(db._resume_lineage_ids(tip))
    narrow = ("role = 'tool' AND tool_call_id = ?" if field == "tool_result"
              else "role = 'assistant' AND tool_calls IS NOT NULL AND instr(tool_calls, ?) > 0")
    sql = (f"SELECT * FROM messages WHERE session_id IN ({', '.join('?' for _ in sessions)})"
           + db._active_clause(False, True) + f" AND {narrow} ORDER BY id ASC")
    with db._read_ctx() as conn:
        rows = conn.execute(sql, (*sessions, tool_call_id)).fetchall()
    return [db._row_to_message_dict(row, warn_context="lineage_tool_rows", summary_flag=True)
            for row in db._dedupe_display_generations(rows)]
