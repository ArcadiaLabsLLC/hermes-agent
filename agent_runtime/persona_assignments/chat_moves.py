"""Which instance a saved chat has MOVED to — the store-side record of a chat move.

A minted chat id names the instance it was made for
(``persona_chat_<instance>_<12 hex>``, :func:`identity.chat_session_owner_instance_id`),
and the bind refuses a chat whose id names another instance (the sibling steal,
live 2026-07-18). Owner 2026-11-19 ("Reuse idle, else new",
``RT-A-SAVED-CHAT-CAN-MOVE-TO-ANOTHER-INSTANCE-OF-ITS-AGENT``): a saved chat may
move to another instance of the SAME agent and stays one conversation — its
transcript row is not copied and its id does not change. So "minted for" and
"held by" can now differ, and this ledger is where the difference is written.

One writer: :func:`record_chat_move`, called only by the move lane
(``agent_runtime.persona_chat_move.move_chat``), which also rewrites the
transcript's own ``persona_instance_id``. The ledger answers the checks that see
only the instance store and a chat id — the bind's sibling-steal refusal and the
default-chat resolver; the transcript's field answers everything that reads the
transcript row. ``persona_chat_session._persona_chat_session_owner`` accepts a
transcript owner that differs from the minted-for instance only when this ledger
records that very move, so a metadata write alone still reassigns nothing.

A chat that moves back to the instance it was minted for drops out of the ledger:
the id says it all again.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from utils import atomic_json_write

from agent_runtime import paths
from agent_runtime.locks import agent_record_write_lock
from agent_runtime.persona_assignments.identity import chat_session_owner_instance_id
from agent_runtime.serde import safe_assignment_text, safe_assignment_token

__layer__ = "stores"

__all__ = [
    "chat_session_held_by",
    "chat_session_is_held_elsewhere",
    "load_chat_moves",
    "record_chat_move",
    "restore_chat_move",
]

_logger = logging.getLogger(__name__)

# (path, mtime_ns, size) -> parsed ledger. The resolver and the bind read the
# ledger on every send; it changes only on a move.
_CACHE: dict[str, tuple[tuple[int, int], dict[str, str]]] = {}


def _ledger_path() -> Path:
    return paths.persona_chat_moves_path()


def load_chat_moves() -> dict[str, str]:
    """``{chat session id: instance id now holding it}``; empty when none moved or unreadable."""

    path = _ledger_path()
    try:
        stat = path.stat()
    except OSError:
        return {}
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(str(path))
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _logger.warning("chat move ledger unreadable path=%s", path, exc_info=True)
        return {}
    moves: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            session = safe_assignment_text(key, limit=200)
            holder = safe_assignment_token(value)
            if session and holder:
                moves[session] = holder
    _CACHE[str(path)] = (stamp, moves)
    return dict(moves)


def chat_session_held_by(session_id: str | None) -> str | None:
    """The instance holding *session_id*: its recorded move, else the instance it was minted for."""

    session = safe_assignment_text(session_id, limit=200)
    if not session:
        return None
    return load_chat_moves().get(session) or chat_session_owner_instance_id(session)


def chat_session_is_held_elsewhere(session_id: str | None, instance_id: str | None) -> bool:
    """The sibling-steal test with moves honoured: minted for another instance AND not moved here."""

    from agent_runtime.persona_assignments.identity import chat_session_is_foreign_to_instance

    if not chat_session_is_foreign_to_instance(session_id, instance_id):
        return False
    session = safe_assignment_text(session_id, limit=200)
    target = safe_assignment_token(instance_id)
    return load_chat_moves().get(session) != target


def record_chat_move(session_id: str, to_instance_id: str) -> str | None:
    """Record that *to_instance_id* now holds *session_id*; returns the previous ledger entry.

    Only the move lane calls this. Moving a chat back to the instance it was
    minted for removes its entry.
    """

    session = safe_assignment_text(session_id, limit=200)
    target = safe_assignment_token(to_instance_id)
    if not session or not target:
        raise ValueError("session_id and to_instance_id are required")
    path = _ledger_path()
    with agent_record_write_lock("chat_moves", "ledger"):
        moves = load_chat_moves()
        previous = moves.get(session)
        if chat_session_owner_instance_id(session) == target:
            moves.pop(session, None)
        else:
            moves[session] = target
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, dict(sorted(moves.items())), indent=2, sort_keys=True)
    _CACHE.pop(str(path), None)
    return previous


def restore_chat_move(session_id: str, previous: str | None) -> None:
    """Put back the ledger entry :func:`record_chat_move` replaced (the move lane's rollback)."""

    session = safe_assignment_text(session_id, limit=200)
    path = _ledger_path()
    with agent_record_write_lock("chat_moves", "ledger"):
        moves = load_chat_moves()
        if previous:
            moves[session] = previous
        else:
            moves.pop(session, None)
        atomic_json_write(path, dict(sorted(moves.items())), indent=2, sort_keys=True)
    _CACHE.pop(str(path), None)
