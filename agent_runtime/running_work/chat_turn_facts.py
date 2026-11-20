"""What a chat-turn row reads beside the journal, one fail-safe helper each: the request a turn
serves, its plan summary, whether it takes a steer, an until-done run's checking pass and pass, a
promotable call, the turn's quiet time and the conversation titles.

Moved out of ``lanes_chat`` (W0-G1 size ceiling); ``lanes_chat`` imports each by name, so a stub on
``lanes_chat.<name>`` still reaches the chat-turn lane.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .rows import _module, bounded_operator_text, work_id_of
from .vocabulary import KIND_DISPATCH, _STATE_DB_FILENAME

__layer__ = "lanes"


def _dispatch_parent(record: dict[str, Any]) -> dict[str, Any]:
    """``{"parent_work_id": "dispatch:<id>"}`` on the turn an agent runs for another agent's request.

    RT-FU-AN-AGENT-REQUESTS-OWN-TURN-NAMES-ITS-REQUEST (review w1118a.58 D3): the request's turn runs
    under ``chat_turn.dispatch_turn_request_id``, so the pairing is read through that spelling's own
    inverse — the same link field a foreground tool call carries to its turn — and a client folds the
    two into one entry instead of drawing two agents. ``{}`` for any other turn, fail-safe.
    """

    try:
        from ..chat_turn import dispatch_id_of_turn_request

        dispatch_id = dispatch_id_of_turn_request(record.get("client_message_id") or record.get("turn_id"))
    except Exception:
        return {}
    return {"parent_work_id": work_id_of(KIND_DISPATCH, dispatch_id)} if dispatch_id else {}


def _plan_progress(items: Any) -> dict[str, Any] | None:
    """The live turn's plan summary, counted by the ``todo_state`` producer's own bounds; fail-safe."""

    try:
        from ..profile_runner.tool_payloads import _todo_plan_progress

        return _todo_plan_progress(items)
    except Exception:  # a cosmetic summary never breaks the row
        return None


def _takes_steer(session_id: str, client_message_id: Any) -> bool:
    """``mission_chat_steer.turn_takes_steer``, fail-safe: a watcher record that cannot be read is no watcher."""

    try:
        from .. import paths
        from ..mission_chat_steer import turn_takes_steer

        return turn_takes_steer(runtime_root=paths.store_root(), session_id=session_id,
                                client_message_id=client_message_id)
    except Exception:
        return False


def _checking_runs() -> list[Any]:
    """``chat_goal.bindings`` that are checking a pass (``checking_since``), fail-safe: unreadable is none."""

    try:
        from ..chat_goal import bindings

        return [bound for bound in bindings() if bound.checking_since]
    except Exception:
        return []


def _run_pass(session_id: str, client_message_id: Any) -> dict[str, Any]:
    """``chat_goal.run_pass``, fail-safe: a binding that cannot be read leaves the row a plain chat turn."""

    try:
        from ..chat_goal import run_pass

        return run_pass(session_id, client_message_id)
    except Exception:
        return {}


def _promotable(turn_id: str, call_id: str) -> bool:
    """A long-call bracket holds this call and has not promoted it yet (``tools/long_tool_calls.py``)."""

    lane = _module("tools.long_tool_calls")
    if lane is None:
        return False
    try:
        return lane.promotable_handle(turn_id, call_id) is not None
    except Exception:  # a cosmetic affordance never breaks the row
        return False


def _turn_quiet(live: Any, current: Any) -> tuple[float | None, str | None]:
    """``(seconds since progress, tool in flight)`` for a live turn.

    Inside a foreground command the agent's own activity stamp is useless: the
    terminal wait touches it every 10 s whether or not the command prints
    anything, so a silent build would read as busy forever. There the quiet
    time is the COMMAND's — seconds since its output last grew.
    """

    if current is not None and current.foreground is not None:
        return current.foreground.seconds_since_output, current.tool_name
    return live.seconds_since_activity, (current.tool_name if current is not None else None)


def _chat_titles(session_ids: set[str]) -> dict[str, str]:
    """``session id -> conversation title`` from each chat's own SessionDB, read-only.

    Cosmetic and fail-safe: a session whose scope or database cannot be read
    simply has no title. Same discipline as the delegation read — an existing
    ``state.db`` opened ``mode=ro``, never created, never migrated — and one
    query per chat home, not per row.
    """

    if not session_ids:
        return {}
    try:
        from ..chat_session_scope import resolve_chat_session_scope
    except Exception:
        return {}
    by_home: dict[Path, list[str]] = {}
    for session_id in sorted(session_ids):
        try:
            home = Path(resolve_chat_session_scope(session_id=session_id).head_home)
        except Exception:
            continue
        by_home.setdefault(home, []).append(session_id)
    titles: dict[str, str] = {}
    for home, ids in by_home.items():
        titles.update(_titles_in(home / _STATE_DB_FILENAME, ids))
    return titles


def _titles_in(db_path: Path, session_ids: list[str]) -> dict[str, str]:
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    except Exception:
        return {}
    try:
        marks = ",".join("?" for _ in session_ids)
        rows = conn.execute(f"SELECT id, title FROM sessions WHERE id IN ({marks})", session_ids).fetchall()
    except Exception:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {str(sid): bounded_operator_text(title, limit=160) for sid, title in rows if title}
