"""Native, revision-pinned history previews and atomic prefix branches.

This is a SessionDB door, not a second transcript store. Rewind remains owned
by SessionRewindMixin; its writer accepts the same revision pin and receipt.
"""
from __future__ import annotations

import hashlib
import json
import time

from hermes_state_titles import next_title_in_lineage


class HistoryControlError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def history_digest(conn, session_id: str) -> str:
    """Pin payloads as well as row membership; metadata changes are conservative."""
    rows = [{key: {"sqlite_blob": value.hex()} if isinstance(value, bytes) else value
             for key, value in dict(row).items()} for row in conn.execute(
        "SELECT * FROM messages WHERE session_id = ? AND active = 1 ORDER BY id", (session_id,))]
    # Native message rows include binary payloads (for example token caches).
    # Tag their lossless representation rather than dropping them from the pin.
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _display_rows(conn, lineage: list[str]):
    """The lineage's display-eligible rows (live plus compaction-archived), by id."""
    return conn.execute(
        f"SELECT * FROM messages WHERE session_id IN ({', '.join('?' for _ in lineage)}) "
        "AND (active = 1 OR compacted = 1) ORDER BY id", tuple(lineage)).fetchall()


def lineage_history_digest(conn, lineage: list[str]) -> str:
    """Pin a branch source: every session of the compression lineage, in order, with its display rows.

    A tip rotated by compression ends the old tip (the writer guard refuses it) and
    adds a session to the lineage (a different digest), so neither branches a moved history.
    """
    def encode(row):
        return {key: {"sqlite_blob": value.hex()} if isinstance(value, bytes) else value
                for key, value in dict(row).items()}

    payload = [[session_id, [encode(row) for row in _display_rows(conn, [session_id])]] for session_id in lineage]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _tool_ids(row) -> tuple[list[str], list[str]]:
    """``(call ids this row makes, call id this row answers)``, by the pairing key replay uses."""
    from agent.message_sanitization import coalesce_tool_call_id

    if row["role"] == "tool":
        answered = coalesce_tool_call_id({"id": row["tool_call_id"]})
        return [], [answered] if answered else []
    try:
        calls = json.loads(row["tool_calls"] or "[]")
    except (TypeError, ValueError):
        calls = []
    made = [coalesce_tool_call_id(call) for call in calls if isinstance(call, dict)]
    return [call_id for call_id in made if call_id], []


def _pairs_whole(prefix, rest) -> bool:
    """No result in the prefix without its call; no call in it whose result was left behind."""
    made, answered = set(), set()
    for row in prefix:
        calls, results = _tool_ids(row)
        made.update(calls)
        answered.update(results)
    later = {call_id for row in rest for call_id in _tool_ids(row)[1]}
    return answered <= made and not ((made - answered) & later)


def check_history_digest(conn, session_id: str, expected: str | None) -> None:
    if expected is not None and history_digest(conn, session_id) != expected:
        raise HistoryControlError("history_changed")


def write_history_receipt(conn, receipt: tuple[str, str] | None) -> None:
    if receipt is not None:
        # The receipt and mutation share a transaction. Never overwrite an old
        # operation with different evidence, even after a lost acknowledgement.
        key, value = receipt
        existing = conn.execute("SELECT value FROM state_meta WHERE key = ?", (key,)).fetchone()
        if existing is not None:
            raise HistoryControlError("operation_already_applied")
        conn.execute("INSERT INTO state_meta(key, value) VALUES (?, ?)", (key, value))


class SessionHistoryControlsMixin:
    def history_control_snapshot(self, session_id: str) -> dict:
        """References and revision only; the native rows retain all message bytes."""
        with self._read_ctx() as conn:
            row = conn.execute("SELECT rewind_count FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return {"revision": history_digest(conn, session_id),
                    "ids": [r[0] for r in conn.execute(
                        "SELECT id FROM messages WHERE session_id = ? AND active = 1 ORDER BY id", (session_id,))],
                    "high_water": conn.execute("SELECT MAX(id) FROM messages WHERE session_id = ?", (session_id,)).fetchone()[0],
                    "rewind_count": row[0] or 0}

    def _check_rewind_redo(self, conn, session_id: str, snapshot: dict, boundary: int) -> str:
        """Reject intervening turns, rewinds, compaction and archived payload edits."""
        rows = [dict(r) for r in conn.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,))]
        count = conn.execute("SELECT rewind_count FROM sessions WHERE id = ?", (session_id,)).fetchone()
        original = set(snapshot["ids"])
        active = [r["id"] for r in rows if r["active"]]
        if (not count or count[0] != snapshot["rewind_count"] + 1
                or (rows[-1]["id"] if rows else None) != snapshot["high_water"]
                or active != [i for i in snapshot["ids"] if i < boundary]):
            raise HistoryControlError("history_changed")
        restored = [{k: {"sqlite_blob": v.hex()} if isinstance(v, bytes) else v
                     for k, v in {**row, "active": 1}.items()} for row in rows if row["id"] in original]
        digest = hashlib.sha256(json.dumps(restored, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        if digest != snapshot["revision"]:
            raise HistoryControlError("history_changed")
        return history_digest(conn, session_id)

    def preview_rewind_redo(self, session_id: str, snapshot: dict, boundary: int) -> str:
        with self._read_ctx() as conn:
            return self._check_rewind_redo(conn, session_id, snapshot, boundary)

    def redo_rewind(self, session_id: str, *, snapshot: dict, boundary: int,
                    expected_history_digest: str, operation_receipt: tuple[str, str]) -> None:
        """Reactivate exactly one reviewed rewind, atomically with its receipt."""
        def apply(conn):
            self._check_transcript_write_guards(conn, session_id, None,
                reject_active_turn_lease=True, reject_active_compression_lock=True)
            check_history_digest(conn, session_id, expected_history_digest)
            self._check_rewind_redo(conn, session_id, snapshot, boundary)
            conn.executemany("UPDATE messages SET active = 1 WHERE session_id = ? AND id = ?",
                             [(session_id, i) for i in snapshot["ids"] if i >= boundary])
            messages, tools = self._active_transcript_counts(conn, session_id)
            conn.execute("UPDATE sessions SET message_count = ?, tool_call_count = ? WHERE id = ?",
                         (messages, tools, session_id))
            write_history_receipt(conn, operation_receipt)
        self._execute_write(apply)

    def archived_history_message_ids(self, session_id: str) -> list[str]:
        """Only identity columns for rewind archives; never reload message bodies."""
        lineage = self._resume_lineage_ids(session_id)
        with self._read_ctx() as conn:
            return [row[0] for row in conn.execute(
                "SELECT platform_message_id FROM messages WHERE session_id IN ("
                + ", ".join("?" for _ in lineage)
                + ") AND active = 0 AND COALESCE(compacted, 0) = 0 AND platform_message_id IS NOT NULL",
                tuple(lineage))]

    def history_control_revision(self, session_id: str) -> str:
        with self._read_ctx() as conn:
            return history_digest(conn, session_id)

    def branch_history_revision(self, session_id: str) -> str:
        """The pin a branch preview hands to :meth:`branch_before_message`: the whole compression lineage."""
        lineage = self._resume_lineage_ids(self.resolve_resume_session_id(session_id))
        with self._read_ctx() as conn:
            return lineage_history_digest(conn, lineage)

    def branch_before_message(
        self, session_id: str, target_message_id: int, *, child_session_id: str,
        expected_history_digest: str, operation_receipt: tuple[str, str],
        model_config: dict, title: str, after_reply: bool = False,
    ) -> str:
        """Clone the exact visible prefix of a chat into a new chat in ONE transaction.

        ``session_id`` is the chat root. Its compression lineage (root -> live tip) is
        resolved here, and the prefix is the lineage's DISPLAY rows — compaction-archived
        ones included, deduped as every display projection dedupes — cut by display
        position before the target (after it for ``after_reply``), so a tool call and its
        result stay together even when compression cloned one of them into a later
        session. The target may sit in any session of the lineage. Rows are cloned live
        and uncompressed; no source session gets a write. Native active leases and
        compression guards run on the tip, and the lineage pin (``branch_history_revision``)
        is checked before anything is inserted. The caller validates a canonical user
        boundary and ownership; this door checks the stored role and display membership too.
        """
        tip = self.resolve_resume_session_id(session_id)
        lineage = self._resume_lineage_ids(tip)

        def apply(conn):
            self._check_transcript_write_guards(
                conn, tip, None, reject_active_turn_lease=True,
                reject_active_compression_lock=True)
            if lineage_history_digest(conn, lineage) != expected_history_digest:
                raise HistoryControlError("history_changed")
            source = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            display = self._dedupe_display_generations(_display_rows(conn, lineage))
            position = next((index for index, row in enumerate(display) if row["id"] == target_message_id), None)
            target = display[position] if position is not None else None
            if source is None or target is None or target["role"] != ("assistant" if after_reply else "user"):
                raise HistoryControlError("target_unavailable")
            cut = position + 1 if after_reply else position
            if not _pairs_whole(display[:cut], display[cut:]):
                raise HistoryControlError("target_unavailable")
            if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (child_session_id,)).fetchone():
                raise HistoryControlError("branch_already_exists")
            # Copy settings/routing explicitly. Lifecycle, counters, read state
            # and cache/session identity belong to the new conversation.
            columns = ("source", "created_source", "model", "system_prompt", "system_prompt_hash",
                       "cwd", "git_repo_root", "git_branch", "profile_name", "transport_profile",
                       "user_id", "chat_type", "origin_json", "display_name")
            copied = {name: source[name] for name in columns if name in source.keys()}
            copied.update(id=child_session_id, parent_session_id=session_id,
                          started_at=time.time(), title=next_title_in_lineage(conn, title),
                          model_config=json.dumps(model_config))
            conn.execute(f"INSERT INTO sessions ({', '.join(copied)}) VALUES "
                         f"({', '.join('?' for _ in copied)})", tuple(copied.values()))
            # One row per clone, in display order: a representative's id need not
            # follow its display position (a live tail copy outranks later rows).
            for row in display[:cut]:
                self._clone_message_rows(conn, [int(row["id"])], session_id=child_session_id)
            message_count, tool_count = self._active_transcript_counts(conn, child_session_id)
            conn.execute("UPDATE sessions SET message_count = ?, tool_call_count = ? WHERE id = ?",
                         (message_count, tool_count, child_session_id))
            write_history_receipt(conn, operation_receipt)
            return child_session_id
        return self._execute_write(apply)
