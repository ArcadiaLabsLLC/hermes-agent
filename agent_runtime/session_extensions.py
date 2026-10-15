"""Fork-specific native compression lineage deletion for a SessionDB.

A free function over upstream's ``SessionDB`` (its ``_execute_write`` and
``_remove_session_files``), not a mixin: ``hermes_state.py`` stays stock.
"""
from pathlib import Path
from typing import Any, List, Optional

__layer__ = "policy"


def delete_compression_lineage(
    db: Any,
    root_session_id: str,
    sessions_dir: Optional[Path] = None,
) -> List[str]:
    """Delete a root and only its native compression continuation chain.

    A child is lineage when its parent ended in ``'compression'`` and upstream's
    non-continuation predicate (``_upstream_doors.non_continuation_child_filter``)
    does not reject it: branch, delegate and reset forks of THAT parent, and
    ``source='tool'`` children, are preserved and detached, matching
    ``delete_session``'s public child semantics.
    """
    from agent_runtime._upstream_doors import non_continuation_child_filter

    child_filter = non_continuation_child_filter("c.")
    parent_binds = child_filter.count("?")
    continuation_sql = (
        "SELECT c.id FROM sessions c JOIN sessions p ON p.id = c.parent_session_id"
        " WHERE c.parent_session_id = ? AND p.end_reason = 'compression'\n" + child_filter
    )
    removed: List[str] = []

    def _do(conn):
        if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (root_session_id,)).fetchone() is None:
            return []
        lineage = {root_session_id}
        frontier = [root_session_id]
        while frontier:
            parent_id = frontier.pop()
            for row in conn.execute(continuation_sql, (parent_id, *([parent_id] * parent_binds))).fetchall():
                if row[0] not in lineage:
                    lineage.add(row[0])
                    frontier.append(row[0])
        ids = sorted(lineage)
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE sessions SET parent_session_id = NULL "
            f"WHERE parent_session_id IN ({placeholders}) AND id NOT IN ({placeholders})",
            tuple(ids + ids),
        )
        conn.execute(f"DELETE FROM messages WHERE session_id IN ({placeholders})", tuple(ids))
        conn.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", tuple(ids))
        removed.extend(ids)
        return ids

    db._execute_write(_do)
    for session_id in removed:
        db._remove_session_files(sessions_dir, session_id)
    return removed



# The source persona scratch turns carried before they adopted upstream's hidden
# ``"tool"`` source (``agent_runtime.persona_runtime.PERSONA_CHAT_SCRATCH_SOURCE``).
# It left upstream's hidden list with that move, so a row still carrying it is
# recall-reachable raw scratch. Retired rows are DELETED, never re-labelled.
RETIRED_SCRATCH_SOURCE = "agent_runtime_persona_chat_scratch"


def purge_retired_scratch_sessions(db: Any, sessions_dir: Optional[Path] = None) -> List[str]:
    """Delete every session still carrying :data:`RETIRED_SCRATCH_SOURCE`.

    Children of a purged row are detached, not deleted (``delete_session``'s
    child semantics). Returns the purged ids so the caller reports the count.
    """

    removed: List[str] = []

    def _do(conn):
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM sessions WHERE source = ?", (RETIRED_SCRATCH_SOURCE,)
            ).fetchall()
        ]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE sessions SET parent_session_id = NULL "
            f"WHERE parent_session_id IN ({placeholders}) AND id NOT IN ({placeholders})",
            tuple(ids + ids),
        )
        conn.execute(f"DELETE FROM messages WHERE session_id IN ({placeholders})", tuple(ids))
        conn.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", tuple(ids))
        removed.extend(ids)
        return ids

    db._execute_write(_do)
    for session_id in removed:
        db._remove_session_files(sessions_dir, session_id)
    return removed
