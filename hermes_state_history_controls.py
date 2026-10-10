"""Native, revision-pinned history previews and atomic prefix branches.

This is a SessionDB door, not a second transcript store. Rewind remains owned
by SessionRewindMixin; its writer accepts the same revision pin and receipt.
"""
from __future__ import annotations

import hashlib
import json
import time


class HistoryControlError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def history_digest(conn, session_id: str) -> str:
    """Pin payloads as well as row membership; metadata changes are conservative."""
    rows = [dict(row) for row in conn.execute(
        "SELECT * FROM messages WHERE session_id = ? AND active = 1 ORDER BY id", (session_id,))]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


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
    def history_control_revision(self, session_id: str) -> str:
        with self._read_ctx() as conn:
            return history_digest(conn, session_id)

    def branch_before_message(
        self, session_id: str, target_message_id: int, *, child_session_id: str,
        expected_history_digest: str, operation_receipt: tuple[str, str],
        model_config: dict, title: str,
    ) -> str:
        """Clone the exact active prefix into a new chat in ONE transaction.

        The source keeps its lifecycle and all message bytes. Native active
        leases/compression guards and the preview revision are checked before
        inserting anything. The caller validates a canonical user boundary and
        ownership; this door checks the stored role and active membership too.
        """
        def apply(conn):
            self._check_transcript_write_guards(
                conn, session_id, None, reject_active_turn_lease=True,
                reject_active_compression_lock=True)
            check_history_digest(conn, session_id, expected_history_digest)
            source = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            target = conn.execute(
                "SELECT role FROM messages WHERE session_id = ? AND id = ? AND active = 1",
                (session_id, target_message_id)).fetchone()
            if source is None or target is None or target[0] != "user":
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
                          started_at=time.time(), title=title, model_config=json.dumps(model_config))
            conn.execute(f"INSERT INTO sessions ({', '.join(copied)}) VALUES "
                         f"({', '.join('?' for _ in copied)})", tuple(copied.values()))
            prefix = [int(row[0]) for row in conn.execute(
                "SELECT id FROM messages WHERE session_id = ? AND active = 1 AND id < ? ORDER BY id",
                (session_id, target_message_id))]
            if prefix:
                self._clone_message_rows(conn, prefix, session_id=child_session_id)
            message_count, tool_count = self._active_transcript_counts(conn, child_session_id)
            conn.execute("UPDATE sessions SET message_count = ?, tool_call_count = ? WHERE id = ?",
                         (message_count, tool_count, child_session_id))
            write_history_receipt(conn, operation_receipt)
            return child_session_id
        return self._execute_write(apply)
